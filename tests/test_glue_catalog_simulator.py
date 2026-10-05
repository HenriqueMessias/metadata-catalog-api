from __future__ import annotations

import pytest

# Dependências opcionais do emulador (requirements-glue-emulator.txt): sem elas, estes
# testes são pulados em vez de quebrar a coleta do `pytest` na instalação padrão.
pytest.importorskip("faker")
pytest.importorskip("moto")

from scripts.glue_emulator.generator import SyntheticColumn, SyntheticTable
from scripts.glue_emulator.glue_catalog import GlueCatalogSimulator


def _table(**overrides) -> SyntheticTable:
    base = dict(
        database_name="sales",
        table_name="orders",
        description="Fact table",
        location="s3://data-lake-sales/orders/",
        owner_name="Henrique",
        owner_email="henrique@example.com",
        domain="sales",
        classification="internal",
        tags=["fact"],
        columns=[SyntheticColumn(name="id", type="string")],
    )
    base.update(overrides)
    return SyntheticTable(**base)


def test_put_table_creates_database_and_table():
    with GlueCatalogSimulator() as catalog:
        catalog.put_table(_table())

        tables = catalog.list_tables("sales")

    assert len(tables) == 1
    assert tables[0]["Name"] == "orders"
    assert tables[0]["DatabaseName"] == "sales"
    assert tables[0]["StorageDescriptor"]["Location"] == "s3://data-lake-sales/orders/"


def test_put_table_is_idempotent_and_overwrites_on_second_call():
    with GlueCatalogSimulator() as catalog:
        catalog.put_table(_table())
        catalog.put_table(_table(description="Updated description"))

        tables = catalog.list_tables("sales")

    assert len(tables) == 1
    assert tables[0]["Description"] == "Updated description"


def test_put_table_reflects_column_changes():
    with GlueCatalogSimulator() as catalog:
        catalog.put_table(_table())
        drifted_columns = [
            SyntheticColumn(name="id", type="string"),
            SyntheticColumn(name="discount", type="double"),
        ]
        catalog.put_table(_table(columns=drifted_columns))

        tables = catalog.list_tables("sales")

    columns = tables[0]["StorageDescriptor"]["Columns"]
    assert [c["Name"] for c in columns] == ["id", "discount"]


def test_list_all_tables_spans_multiple_databases():
    with GlueCatalogSimulator() as catalog:
        catalog.put_table(_table(database_name="sales", table_name="orders"))
        catalog.put_table(_table(database_name="marketing", table_name="campaigns"))

        tables = catalog.list_all_tables()

    identities = {(t["DatabaseName"], t["Name"]) for t in tables}
    assert identities == {("sales", "orders"), ("marketing", "campaigns")}


def test_parameters_carry_synthetic_owner_and_classification():
    with GlueCatalogSimulator() as catalog:
        catalog.put_table(_table(owner_email="steward@example.com", classification="restricted"))

        tables = catalog.list_tables("sales")

    assert tables[0]["Parameters"]["owner_email"] == "steward@example.com"
    assert tables[0]["Parameters"]["data_classification"] == "restricted"
