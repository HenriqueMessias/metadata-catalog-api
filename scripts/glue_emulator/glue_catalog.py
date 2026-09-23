"""A mocked AWS Glue Data Catalog, behind the real `boto3` client interface.

Code that reads from this (`sync.py`, indirectly `mapper.py`) makes exactly
the same `boto3` calls it would make against a real AWS account -- only the
mocked credentials/context differ. Swapping this for a real Glue catalog
later needs no changes to the reading code (SDD, section 4 decision B).
"""

from __future__ import annotations

from typing import Any

import boto3
from moto import mock_aws

from scripts.glue_emulator.generator import SyntheticTable


class GlueCatalogSimulator:
    """Context manager wrapping a `moto`-mocked Glue Data Catalog."""

    def __init__(self, region_name: str = "us-east-1"):
        self._mock = mock_aws()
        self._region_name = region_name
        self._client = None

    def __enter__(self) -> "GlueCatalogSimulator":
        self._mock.start()
        self._client = boto3.client("glue", region_name=self._region_name)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._client = None
        self._mock.stop()

    @property
    def client(self):
        if self._client is None:
            raise RuntimeError("GlueCatalogSimulator must be used as a context manager")
        return self._client

    def ensure_database(self, name: str) -> None:
        existing = {db["Name"] for db in self.client.get_databases()["DatabaseList"]}
        if name not in existing:
            self.client.create_database(DatabaseInput={"Name": name})

    def put_table(self, table: SyntheticTable) -> None:
        """Creates the table if it doesn't exist yet, otherwise overwrites
        it -- simulating a crawler re-running over the same S3 location and
        finding an updated schema.
        """
        self.ensure_database(table.database_name)
        table_input = self._to_table_input(table)
        try:
            self.client.create_table(DatabaseName=table.database_name, TableInput=table_input)
        except self.client.exceptions.AlreadyExistsException:
            self.client.update_table(DatabaseName=table.database_name, TableInput=table_input)

    def list_tables(self, database_name: str) -> list[dict[str, Any]]:
        tables: list[dict[str, Any]] = []
        paginator = self.client.get_paginator("get_tables")
        for page in paginator.paginate(DatabaseName=database_name):
            for table in page["TableList"]:
                # Real Glue always includes DatabaseName on a Table; moto's
                # fidelity to that isn't guaranteed, so set it defensively.
                table.setdefault("DatabaseName", database_name)
                tables.append(table)
        return tables

    def list_all_tables(self) -> list[dict[str, Any]]:
        tables: list[dict[str, Any]] = []
        for database in self.client.get_databases()["DatabaseList"]:
            tables.extend(self.list_tables(database["Name"]))
        return tables

    @staticmethod
    def _to_table_input(table: SyntheticTable) -> dict[str, Any]:
        return {
            "Name": table.table_name,
            "Description": table.description,
            # Glue's *native* Owner is just a free-text string, usually an
            # IAM identity -- not a structured contact. See the SDD's field
            # mapping table (section 5) for why owner.name/email instead
            # come from Parameters below.
            "Owner": "glue-crawler-role",
            "StorageDescriptor": {
                "Columns": [{"Name": column.name, "Type": column.type} for column in table.columns],
                "Location": table.location,
            },
            "Parameters": {
                "owner_name": table.owner_name,
                "owner_email": table.owner_email,
                "domain": table.domain,
                "data_classification": table.classification,
                "tags": ",".join(table.tags),
            },
        }
