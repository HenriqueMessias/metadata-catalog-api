"""CLI entrypoint. See docs/sdd-glue-catalog-emulator.md, section 6, for what
each mode does and why.
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from scripts.glue_emulator.generator import SyntheticTable, TableGenerator
from scripts.glue_emulator.glue_catalog import GlueCatalogSimulator
from scripts.glue_emulator.sync import CatalogSyncClient, SyncStats


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-url", default="http://localhost:8000/api/v1", help="Data Catalog API base URL")
    common.add_argument("--tables", type=int, default=200, help="Number of synthetic tables to generate")
    common.add_argument(
        "--databases", type=int, default=5, help="Number of synthetic databases to spread tables across"
    )
    common.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible generation. Pass the SAME value (and --tables/"
        "--databases) used in a prior seed/drift run so drift/rerun regenerate the "
        "identical tables -- the mocked Glue catalog is in-memory per process and does "
        "not persist across separate CLI invocations, unlike the Mongo-backed API.",
    )

    parser = argparse.ArgumentParser(
        prog="glue_emulator",
        description="Emulates an AWS Glue Data Catalog (via moto) and syncs synthetic "
        "table metadata into the Data Catalog API. See docs/sdd-glue-catalog-emulator.md.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    subparsers.add_parser("seed", parents=[common], help="Create N synthetic tables and sync them to the API")

    drift_parser = subparsers.add_parser(
        "drift", parents=[common], help="Seed, then simulate a re-crawl that changes a fraction of tables' schemas"
    )
    drift_parser.add_argument("--ratio", type=float, default=0.2, help="Fraction of tables to drift (0-1)")

    subparsers.add_parser("load", parents=[common], help="Like seed, but times the sync and reports throughput")

    subparsers.add_parser(
        "rerun",
        parents=[common],
        help="Re-run the same generation and sync again, to validate idempotency "
        "(expects 409s, not new records -- pass the same --seed as the prior run)",
    )

    return parser


def _generate_batch(
    generator: TableGenerator, catalog: GlueCatalogSimulator, table_count: int, database_count: int, rng: random.Random
) -> list[SyntheticTable]:
    database_names = [generator.generate_database_name() for _ in range(database_count)]
    tables: list[SyntheticTable] = []
    for _ in range(table_count):
        database_name = rng.choice(database_names)
        table = generator.generate_table(database_name)
        catalog.put_table(table)
        tables.append(table)
    return tables


def _print_stats(label: str, stats: SyncStats) -> None:
    print(
        f"[{label}] created={stats.created} updated={stats.updated} "
        f"conflicts(409)={stats.unchanged_conflicts} failed={stats.failed}"
    )
    for error in stats.errors[:10]:
        print(f"  ! {error}")
    if len(stats.errors) > 10:
        print(f"  ... and {len(stats.errors) - 10} more errors")


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    generator = TableGenerator(seed=args.seed)
    rng = random.Random(args.seed)

    with GlueCatalogSimulator() as catalog, CatalogSyncClient(args.api_url) as sync_client:
        synthetic_tables = _generate_batch(generator, catalog, args.tables, args.databases, rng)
        glue_tables = catalog.list_all_tables()

        if args.mode == "load":
            start = time.perf_counter()
            stats = sync_client.sync_all(glue_tables)
            elapsed = time.perf_counter() - start
            _print_stats("load", stats)
            throughput = stats.total / elapsed if elapsed > 0 else float("inf")
            print(f"[load] {stats.total} tables in {elapsed:.2f}s ({throughput:.1f} req/s)")
            return 0 if stats.failed == 0 else 1

        stats = sync_client.sync_all(glue_tables)
        _print_stats(args.mode, stats)

        if args.mode == "drift":
            sample_size = max(1, int(len(synthetic_tables) * args.ratio))
            drifted_tables = rng.sample(synthetic_tables, k=min(sample_size, len(synthetic_tables)))
            for table in drifted_tables:
                table.columns = generator.drift_columns(table.columns)
                catalog.put_table(table)

            drifted_identities = {(table.database_name, table.table_name) for table in drifted_tables}
            resync_targets = [
                glue_table
                for glue_table in catalog.list_all_tables()
                if (glue_table["DatabaseName"], glue_table["Name"]) in drifted_identities
            ]
            drift_stats = sync_client.sync_all(resync_targets)
            _print_stats("drift (re-sync)", drift_stats)
            print(f"[drift] {len(drifted_tables)}/{len(synthetic_tables)} tables had a column added/removed")
            stats = drift_stats

        if args.mode == "rerun":
            if stats.created > 0:
                print(
                    f"[rerun] WARNING: {stats.created} tables were newly created -- pass the "
                    "same --seed/--tables/--databases as the prior seed/drift run to actually "
                    "test idempotency against existing data"
                )
            else:
                print(f"[rerun] idempotency OK: no new records created ({stats.unchanged_conflicts} conflicts as expected)")

    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
