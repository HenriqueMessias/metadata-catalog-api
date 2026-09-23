from __future__ import annotations

import pytest

from app.exceptions import DuplicateMetadataError, MetadataNotFoundError
from app.models.metadata import ColumnSchema, MetadataCreate, MetadataUpdate
from app.services.metadata_service import MetadataService


@pytest.mark.asyncio
async def test_create_persists_metadata_with_initial_schema_version(
    service: MetadataService, sample_payload: MetadataCreate
):
    created = await service.create(sample_payload)

    assert created.id is not None
    assert created.table_name == "orders"
    assert created.schema_version == 1
    assert created.schema_history == []


@pytest.mark.asyncio
async def test_create_rejects_duplicate_table_identity(
    service: MetadataService, sample_payload: MetadataCreate
):
    await service.create(sample_payload)

    with pytest.raises(DuplicateMetadataError):
        await service.create(sample_payload)


@pytest.mark.asyncio
async def test_get_raises_not_found_for_unknown_id(service: MetadataService):
    with pytest.raises(MetadataNotFoundError):
        await service.get("507f1f77bcf86cd799439011")


@pytest.mark.asyncio
async def test_update_without_column_changes_keeps_schema_version(
    service: MetadataService, sample_payload: MetadataCreate
):
    created = await service.create(sample_payload)

    updated = await service.update(
        created.id, MetadataUpdate(description="Updated description", updated_by="henrique")
    )

    assert updated.description == "Updated description"
    assert updated.schema_version == 1
    assert updated.schema_history == []


@pytest.mark.asyncio
async def test_update_with_column_changes_bumps_schema_version_and_records_history(
    service: MetadataService, sample_payload: MetadataCreate
):
    created = await service.create(sample_payload)
    new_columns = [
        *created.columns,
        ColumnSchema(name="discount", data_type="FLOAT64", nullable=True),
    ]

    updated = await service.update(
        created.id, MetadataUpdate(columns=new_columns, updated_by="henrique")
    )

    assert updated.schema_version == 2
    assert len(updated.schema_history) == 1
    assert updated.schema_history[0].version == 1
    assert len(updated.schema_history[0].columns) == 3  # original column set, frozen
    assert len(updated.columns) == 4


@pytest.mark.asyncio
async def test_update_raises_not_found_for_unknown_id(service: MetadataService):
    with pytest.raises(MetadataNotFoundError):
        await service.update("507f1f77bcf86cd799439011", MetadataUpdate(description="x"))


@pytest.mark.asyncio
async def test_delete_removes_metadata(service: MetadataService, sample_payload: MetadataCreate):
    created = await service.create(sample_payload)

    await service.delete(created.id)

    with pytest.raises(MetadataNotFoundError):
        await service.get(created.id)


@pytest.mark.asyncio
async def test_delete_raises_not_found_for_unknown_id(service: MetadataService):
    with pytest.raises(MetadataNotFoundError):
        await service.delete("507f1f77bcf86cd799439011")


@pytest.mark.asyncio
async def test_list_filters_by_tag(service: MetadataService, sample_payload: MetadataCreate):
    await service.create(sample_payload)
    other = sample_payload.model_copy(update={"table_name": "invoices", "tags": ["billing"]})
    await service.create(other)

    items, total = await service.list(tag="fact")

    assert total == 1
    assert items[0].table_name == "orders"
