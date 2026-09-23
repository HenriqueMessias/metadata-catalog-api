from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.metadata import MetadataInDB


class MetadataRepository(ABC):
    """Port (in the hexagonal-architecture sense) for metadata persistence.

    The service layer depends on this abstraction only, never on Motor/MongoDB
    directly. That is what lets `MetadataService` be unit-tested with a plain
    in-memory fake instead of a real database (see tests/fakes.py).
    """

    @abstractmethod
    async def create(self, metadata: MetadataInDB) -> MetadataInDB: ...

    @abstractmethod
    async def get_by_id(self, metadata_id: str) -> MetadataInDB | None: ...

    @abstractmethod
    async def find_by_identity(
        self, database_name: str, schema_name: str, table_name: str
    ) -> MetadataInDB | None: ...

    @abstractmethod
    async def list(
        self,
        skip: int,
        limit: int,
        owner_email: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> tuple[list[MetadataInDB], int]: ...

    @abstractmethod
    async def update(self, metadata_id: str, metadata: MetadataInDB) -> MetadataInDB | None: ...

    @abstractmethod
    async def delete(self, metadata_id: str) -> bool: ...
