from __future__ import annotations

from app.exceptions import DuplicateMetadataError, MetadataNotFoundError
from app.models.metadata import (
    MetadataCreate,
    MetadataInDB,
    MetadataUpdate,
    SchemaVersionEntry,
    utcnow,
)
from app.repositories.base import MetadataRepository


class MetadataService:
    """Business logic for the metadata catalog.

    Depends on the `MetadataRepository` abstraction (dependency inversion),
    so it never touches Motor/MongoDB directly and can be unit-tested with an
    in-memory fake repository.
    """

    def __init__(self, repository: MetadataRepository):
        self._repository = repository

    async def create(self, payload: MetadataCreate) -> MetadataInDB:
        existing = await self._repository.find_by_identity(
            payload.database_name, payload.schema_name, payload.table_name
        )
        if existing is not None:
            raise DuplicateMetadataError(
                payload.database_name, payload.schema_name, payload.table_name
            )

        metadata = MetadataInDB(**payload.model_dump())
        return await self._repository.create(metadata)

    async def get(self, metadata_id: str) -> MetadataInDB:
        metadata = await self._repository.get_by_id(metadata_id)
        if metadata is None:
            raise MetadataNotFoundError(metadata_id)
        return metadata

    async def list(
        self,
        skip: int = 0,
        limit: int = 20,
        owner_email: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> tuple[list[MetadataInDB], int]:
        return await self._repository.list(
            skip=skip,
            limit=limit,
            owner_email=owner_email,
            domain=domain,
            tag=tag,
            search=search,
        )

    async def update(self, metadata_id: str, payload: MetadataUpdate) -> MetadataInDB:
        current = await self._repository.get_by_id(metadata_id)
        if current is None:
            raise MetadataNotFoundError(metadata_id)

        updates = payload.model_dump(exclude_unset=True, exclude={"updated_by"})
        columns_changed = "columns" in updates and updates["columns"] != [
            column.model_dump() for column in current.columns
        ]

        # `model_copy(update=...)` does not re-validate/coerce nested models, so
        # merge-and-revalidate instead: keeps `columns` as real `ColumnSchema`
        # instances rather than raw dicts.
        merged = current.model_dump(by_alias=True)
        merged.update(updates)
        updated = MetadataInDB.model_validate(merged)
        updated.updated_at = utcnow()
        updated.updated_by = payload.updated_by

        if columns_changed:
            # Freeze the version being superseded before bumping.
            updated.schema_history = [
                *current.schema_history,
                SchemaVersionEntry(
                    version=current.schema_version,
                    columns=current.columns,
                    changed_at=current.updated_at,
                    changed_by=current.updated_by,
                ),
            ]
            updated.schema_version = current.schema_version + 1

        result = await self._repository.update(metadata_id, updated)
        if result is None:
            raise MetadataNotFoundError(metadata_id)
        return result

    async def delete(self, metadata_id: str) -> None:
        deleted = await self._repository.delete(metadata_id)
        if not deleted:
            raise MetadataNotFoundError(metadata_id)
