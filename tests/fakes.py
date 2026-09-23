from __future__ import annotations

from bson import ObjectId

from app.exceptions import DuplicateMetadataError
from app.models.metadata import MetadataInDB
from app.repositories.base import MetadataRepository


class InMemoryMetadataRepository(MetadataRepository):
    """Fake adapter used by tests, in place of a real MongoDB instance.

    Because `MetadataService` only depends on the `MetadataRepository`
    abstraction, this fake is a drop-in replacement: it lets the whole
    service layer (and, via dependency override, the API layer) be tested
    fast and deterministically, with no external infrastructure.
    """

    def __init__(self):
        self._store: dict[str, MetadataInDB] = {}

    async def create(self, metadata: MetadataInDB) -> MetadataInDB:
        if await self.find_by_identity(metadata.database_name, metadata.schema_name, metadata.table_name):
            raise DuplicateMetadataError(metadata.database_name, metadata.schema_name, metadata.table_name)
        metadata_id = str(ObjectId())
        stored = metadata.model_copy(update={"id": metadata_id})
        self._store[metadata_id] = stored
        return stored

    async def get_by_id(self, metadata_id: str) -> MetadataInDB | None:
        return self._store.get(metadata_id)

    async def find_by_identity(
        self, database_name: str, schema_name: str, table_name: str
    ) -> MetadataInDB | None:
        for item in self._store.values():
            if (
                item.database_name == database_name
                and item.schema_name == schema_name
                and item.table_name == table_name
            ):
                return item
        return None

    async def list(
        self,
        skip: int,
        limit: int,
        owner_email: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> tuple[list[MetadataInDB], int]:
        items = list(self._store.values())
        if owner_email:
            items = [item for item in items if item.owner.email == owner_email]
        if domain:
            items = [item for item in items if item.domain == domain]
        if tag:
            items = [item for item in items if tag in item.tags]
        if search:
            items = [item for item in items if search.lower() in item.table_name.lower()]
        items.sort(key=lambda item: item.table_name)
        total = len(items)
        return items[skip : skip + limit], total

    async def update(self, metadata_id: str, metadata: MetadataInDB) -> MetadataInDB | None:
        if metadata_id not in self._store:
            return None
        duplicate = await self.find_by_identity(
            metadata.database_name, metadata.schema_name, metadata.table_name
        )
        if duplicate is not None and duplicate.id != metadata_id:
            raise DuplicateMetadataError(metadata.database_name, metadata.schema_name, metadata.table_name)
        stored = metadata.model_copy(update={"id": metadata_id})
        self._store[metadata_id] = stored
        return stored

    async def delete(self, metadata_id: str) -> bool:
        return self._store.pop(metadata_id, None) is not None
