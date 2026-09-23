"""Translates a Glue `Table` dict (as returned by `glue.get_tables()`) into
the Data Catalog API's request contract.

See the SDD's field-mapping table (docs/sdd-glue-catalog-emulator.md,
section 5) for the reasoning behind each mapping decision.
"""

from __future__ import annotations

from typing import Any

from app.models.metadata import ColumnSchema, DataClassification, MetadataCreate, MetadataUpdate, Owner

# Glue has no third namespace level (Database -> Table only); we document
# this fixed convention rather than force a field that doesn't exist there.
SCHEMA_NAME = "glue"

# Fixed until the API authentication SDD (docs/sdd-api-authentication.md) is
# implemented -- at that point this value stops being a literal and instead
# comes from a client-credentials token.
SYNC_ACTOR = "glue-emulator"


def _columns_from_glue(glue_table: dict[str, Any]) -> list[ColumnSchema]:
    raw_columns = glue_table.get("StorageDescriptor", {}).get("Columns", [])
    return [
        ColumnSchema(name=column["Name"], data_type=column["Type"], nullable=True)
        for column in raw_columns
    ]


def _owner_from_glue(parameters: dict[str, str]) -> Owner:
    # Table['Owner'] (the native Glue field) is a free-text string, usually
    # an IAM identity -- not a contact. Structured owner info instead comes
    # from Parameters, simulating a crawler enriched by internal convention.
    return Owner(
        name=parameters.get("owner_name") or "unknown",
        email=parameters.get("owner_email") or "unknown@example.com",
    )


def _classification_from_glue(parameters: dict[str, str]) -> DataClassification:
    # Not to be confused with Glue's *native* Classification field on
    # StorageDescriptor, which describes file format (csv/parquet/...), not
    # sensitivity -- see the SDD's field-mapping table (section 5).
    value = parameters.get("data_classification", DataClassification.INTERNAL.value)
    try:
        return DataClassification(value)
    except ValueError:
        return DataClassification.INTERNAL


def _tags_from_glue(parameters: dict[str, str]) -> list[str]:
    return [tag for tag in parameters.get("tags", "").split(",") if tag]


def to_metadata_create(glue_table: dict[str, Any]) -> MetadataCreate:
    parameters = glue_table.get("Parameters") or {}
    return MetadataCreate(
        table_name=glue_table["Name"],
        database_name=glue_table["DatabaseName"],
        schema_name=SCHEMA_NAME,
        description=glue_table.get("Description"),
        owner=_owner_from_glue(parameters),
        domain=parameters.get("domain"),
        classification=_classification_from_glue(parameters),
        tags=_tags_from_glue(parameters),
        columns=_columns_from_glue(glue_table),
        location=glue_table.get("StorageDescriptor", {}).get("Location"),
        created_by=SYNC_ACTOR,
    )


def to_metadata_update(glue_table: dict[str, Any]) -> MetadataUpdate:
    parameters = glue_table.get("Parameters") or {}
    return MetadataUpdate(
        description=glue_table.get("Description"),
        owner=_owner_from_glue(parameters),
        domain=parameters.get("domain"),
        classification=_classification_from_glue(parameters),
        tags=_tags_from_glue(parameters),
        columns=_columns_from_glue(glue_table),
        location=glue_table.get("StorageDescriptor", {}).get("Location"),
        updated_by=SYNC_ACTOR,
    )
