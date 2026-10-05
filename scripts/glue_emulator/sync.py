"""Talks to the Data Catalog API over HTTP. The only piece of the emulator
that knows about the network -- `glue_catalog.py` and `mapper.py` don't.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from scripts.glue_emulator import mapper


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    unchanged_conflicts: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged_conflicts + self.failed


class CatalogSyncClient:
    """`token` is a Bearer JWT, required by the API's write routes
    (docs/sdd-api-authentication.md, section 7); reads are public. Left unset,
    requests go out unauthenticated, exactly as before authentication existed.
    """

    def __init__(
        self,
        api_base_url: str,
        timeout: float = 10.0,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(
            base_url=api_base_url.rstrip("/"), timeout=timeout, headers=headers, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CatalogSyncClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def find_existing_id(self, database_name: str, schema_name: str, table_name: str) -> str | None:
        """The API has no exact-identity lookup (SDD, section 4): list by a
        `search` substring match on table_name, then filter client-side for
        the exact triple. O(n) per table -- a documented, accepted
        limitation for this emulator's volumes (SDD, section 10).
        """
        response = self._client.get("/metadata", params={"search": table_name, "limit": 100})
        response.raise_for_status()
        for item in response.json()["items"]:
            if (
                item["database_name"] == database_name
                and item["schema_name"] == schema_name
                and item["table_name"] == table_name
            ):
                return item["id"]
        return None

    def sync_table(self, glue_table: dict[str, Any], stats: SyncStats) -> None:
        database_name = glue_table["DatabaseName"]
        table_name = glue_table["Name"]

        try:
            existing_id = self.find_existing_id(database_name, mapper.SCHEMA_NAME, table_name)

            if existing_id is None:
                payload = mapper.to_metadata_create(glue_table)
                response = self._client.post("/metadata", json=payload.model_dump(mode="json"))
                if response.status_code == 409:
                    stats.unchanged_conflicts += 1
                    return
                response.raise_for_status()
                stats.created += 1
            else:
                payload = mapper.to_metadata_update(glue_table)
                response = self._client.put(
                    f"/metadata/{existing_id}", json=payload.model_dump(mode="json")
                )
                response.raise_for_status()
                stats.updated += 1
        except httpx.HTTPStatusError as exc:
            stats.failed += 1
            stats.errors.append(
                f"{database_name}.{table_name}: {exc.response.status_code} {exc.response.text}"
            )
        except httpx.HTTPError as exc:
            stats.failed += 1
            stats.errors.append(f"{database_name}.{table_name}: {exc!r}")

    def sync_all(self, glue_tables: list[dict[str, Any]]) -> SyncStats:
        stats = SyncStats()
        for glue_table in glue_tables:
            self.sync_table(glue_table, stats)
        return stats
