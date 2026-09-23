"""Synthetic, plausible table definitions -- not Glue-shaped yet.

Deliberately knows nothing about the Glue API or the Data Catalog API: it
just produces data. `glue_catalog.py` is the layer that turns this into the
shape a real `boto3` Glue client would return (see the SDD, section 4).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from faker import Faker

HIVE_TYPES = [
    "string",
    "bigint",
    "int",
    "double",
    "float",
    "boolean",
    "timestamp",
    "date",
    "decimal(18,2)",
]
DOMAINS = ["sales", "marketing", "finance", "logistics", "hr", "product", "support"]
CLASSIFICATIONS = ["public", "internal", "confidential", "restricted"]
TAGS_POOL = ["core", "fact", "dimension", "pii", "derived", "raw", "curated", "deprecated"]


@dataclass
class SyntheticColumn:
    name: str
    type: str


@dataclass
class SyntheticTable:
    database_name: str
    table_name: str
    description: str
    location: str
    owner_name: str
    owner_email: str
    domain: str
    classification: str
    tags: list[str]
    columns: list[SyntheticColumn] = field(default_factory=list)


class TableGenerator:
    """Produces synthetic table definitions and simulates schema drift.

    A `seed` makes generation reproducible -- needed so `drift`/`rerun` can
    regenerate the identical tables a prior `seed` run produced, since the
    mocked Glue catalog is in-memory per process and does not persist across
    separate CLI invocations (unlike the Mongo-backed API).
    """

    def __init__(self, seed: int | None = None):
        self._fake = Faker()
        self._random = random.Random(seed)
        Faker.seed(seed)

    def generate_database_name(self) -> str:
        return f"{self._random.choice(DOMAINS)}_{self._fake.word()}".lower()

    def generate_table(self, database_name: str) -> SyntheticTable:
        table_name = f"{self._fake.word()}_{self._fake.word()}".lower()
        return SyntheticTable(
            database_name=database_name,
            table_name=table_name,
            description=self._fake.sentence(nb_words=10),
            location=f"s3://data-lake-{database_name}/{table_name}/",
            owner_name=self._fake.name(),
            owner_email=self._fake.email(),
            domain=self._random.choice(DOMAINS),
            classification=self._random.choice(CLASSIFICATIONS),
            tags=self._random.sample(TAGS_POOL, k=self._random.randint(1, 3)),
            columns=self._generate_columns(),
        )

    def drift_columns(self, columns: list[SyntheticColumn]) -> list[SyntheticColumn]:
        """Simulates a re-crawl that found a schema change: always adds a
        new column and, with lower probability, also drops one (never the
        primary key) -- so most drifted tables grow, some also shrink.
        """
        new_columns = list(columns)
        existing_names = {column.name for column in new_columns}

        new_name = self._fake.word().lower()
        while new_name in existing_names:
            new_name = self._fake.word().lower()
        new_columns.append(SyntheticColumn(name=new_name, type=self._random.choice(HIVE_TYPES)))

        # Never remove the column just added above -- that would net out to
        # no change at all, silently defeating "drift" for this table (a
        # real bug caught by running the emulator end-to-end against a live
        # API: one table's before/after column set came out identical).
        removable = [column for column in new_columns if column.name not in ("id", new_name)]
        if removable and self._random.random() < 0.3:
            to_remove = self._random.choice(removable)
            new_columns = [column for column in new_columns if column.name != to_remove.name]

        return new_columns

    def _generate_columns(self, min_columns: int = 3, max_columns: int = 12) -> list[SyntheticColumn]:
        count = self._random.randint(min_columns, max_columns)
        names = {"id"}
        columns = [SyntheticColumn(name="id", type="string")]
        while len(columns) < count:
            name = self._fake.word().lower()
            if name in names:
                continue
            names.add(name)
            columns.append(SyntheticColumn(name=name, type=self._random.choice(HIVE_TYPES)))
        return columns
