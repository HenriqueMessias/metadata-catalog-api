from __future__ import annotations

from app.models.metadata import DataClassification
from scripts.glue_emulator import mapper


def _glue_table(**overrides) -> dict:
    base = {
        "Name": "orders",
        "DatabaseName": "sales",
        "Description": "Fact table with one row per order.",
        "Owner": "glue-crawler-role",
        "StorageDescriptor": {
            "Columns": [
                {"Name": "id", "Type": "string"},
                {"Name": "amount", "Type": "double"},
            ],
            "Location": "s3://data-lake-sales/orders/",
        },
        "Parameters": {
            "owner_name": "Henrique Messias",
            "owner_email": "henrique@example.com",
            "domain": "sales",
            "data_classification": "confidential",
            "tags": "fact,core",
        },
    }
    base.update(overrides)
    return base


def test_to_metadata_create_maps_identity_and_location():
    payload = mapper.to_metadata_create(_glue_table())

    assert payload.table_name == "orders"
    assert payload.database_name == "sales"
    assert payload.schema_name == mapper.SCHEMA_NAME
    assert payload.location == "s3://data-lake-sales/orders/"
    assert payload.created_by == mapper.SYNC_ACTOR


def test_to_metadata_create_maps_columns():
    payload = mapper.to_metadata_create(_glue_table())

    assert [c.name for c in payload.columns] == ["id", "amount"]
    assert [c.data_type for c in payload.columns] == ["string", "double"]
    assert all(c.nullable for c in payload.columns)


def test_to_metadata_create_maps_owner_from_parameters_not_native_owner_field():
    payload = mapper.to_metadata_create(_glue_table())

    assert payload.owner.name == "Henrique Messias"
    assert payload.owner.email == "henrique@example.com"


def test_to_metadata_create_maps_domain_and_tags():
    payload = mapper.to_metadata_create(_glue_table())

    assert payload.domain == "sales"
    assert payload.tags == ["fact", "core"]


def test_classification_does_not_read_glue_native_classification_field():
    # Glue's native `Classification` (file format, e.g. "parquet") must be
    # ignored -- our `classification` (sensitivity) comes only from Parameters.
    glue_table = _glue_table(Classification="parquet")
    glue_table["Parameters"]["data_classification"] = "restricted"

    payload = mapper.to_metadata_create(glue_table)

    assert payload.classification == DataClassification.RESTRICTED


def test_missing_parameters_fall_back_to_safe_defaults():
    glue_table = _glue_table(Parameters={})

    payload = mapper.to_metadata_create(glue_table)

    assert payload.owner.name == "unknown"
    assert payload.owner.email == "unknown@example.com"
    assert payload.classification == DataClassification.INTERNAL
    assert payload.tags == []
    assert payload.domain is None


def test_table_with_no_columns_maps_to_empty_list():
    glue_table = _glue_table()
    glue_table["StorageDescriptor"]["Columns"] = []

    payload = mapper.to_metadata_create(glue_table)

    assert payload.columns == []


def test_invalid_classification_value_falls_back_to_internal():
    glue_table = _glue_table()
    glue_table["Parameters"]["data_classification"] = "not-a-real-classification"

    payload = mapper.to_metadata_create(glue_table)

    assert payload.classification == DataClassification.INTERNAL


def test_to_metadata_update_sets_updated_by_and_omits_identity_fields():
    payload = mapper.to_metadata_update(_glue_table())

    assert payload.updated_by == mapper.SYNC_ACTOR
    assert payload.description == "Fact table with one row per order."
    assert payload.columns is not None and len(payload.columns) == 2
