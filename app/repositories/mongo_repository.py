from __future__ import annotations

import re

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.exceptions import DuplicateMetadataError
from app.models.metadata import MetadataInDB
from app.repositories.base import MetadataRepository


class MongoMetadataRepository(MetadataRepository):
    """MongoDB (Motor) adapter implementing the `MetadataRepository` port."""

    def __init__(self, collection: AsyncIOMotorCollection):
        self._collection = collection

    async def create(self, metadata: MetadataInDB) -> MetadataInDB:
        document = metadata.to_mongo()
        try:
            result = await self._collection.insert_one(document)
        except DuplicateKeyError as exc:
            raise DuplicateMetadataError(
                metadata.database_name, metadata.schema_name, metadata.table_name
            ) from exc
        document["_id"] = result.inserted_id
        return MetadataInDB.model_validate(document)

    async def get_by_id(self, metadata_id: str) -> MetadataInDB | None:
        object_id = self._to_object_id(metadata_id)
        if object_id is None:
            return None
        document = await self._collection.find_one({"_id": object_id})
        return MetadataInDB.model_validate(document) if document else None

    async def find_by_identity(
        self, database_name: str, schema_name: str, table_name: str
    ) -> MetadataInDB | None:
        document = await self._collection.find_one(
            {
                "database_name": database_name,
                "schema_name": schema_name,
                "table_name": table_name,
            }
        )
        return MetadataInDB.model_validate(document) if document else None

    async def list(
        self,
        skip: int,
        limit: int,
        owner_email: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> tuple[list[MetadataInDB], int]:
        query = self._build_filter(owner_email=owner_email, domain=domain, tag=tag, search=search)

        total = await self._collection.count_documents(query)
        cursor = (
            self._collection.find(query)
            .sort("table_name", 1)
            .skip(skip)
            .limit(limit)
        )
        documents = [MetadataInDB.model_validate(doc) async for doc in cursor]
        return documents, total

    async def update(self, metadata_id: str, metadata: MetadataInDB) -> MetadataInDB | None:
        object_id = self._to_object_id(metadata_id)
        if object_id is None:
            return None
        document = metadata.to_mongo()
        document.pop("_id", None)
        try:
            result = await self._collection.find_one_and_update(
                {"_id": object_id},
                {"$set": document},
                return_document=True,
            )
        except DuplicateKeyError as exc:
            raise DuplicateMetadataError(
                metadata.database_name, metadata.schema_name, metadata.table_name
            ) from exc
        return MetadataInDB.model_validate(result) if result else None

    async def delete(self, metadata_id: str) -> bool:
        object_id = self._to_object_id(metadata_id)
        if object_id is None:
            return False
        result = await self._collection.delete_one({"_id": object_id})
        return result.deleted_count > 0

    @staticmethod
    def _build_filter(
        owner_email: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> dict:
        query: dict = {}
        if owner_email:
            query["owner.email"] = owner_email
        if domain:
            query["domain"] = domain
        if tag:
            query["tags"] = tag
        if search:
            # `search` is a case-insensitive *substring* match (same contract as
            # the in-memory fake), never a user-supplied regex: unescaped input
            # like "(" is an invalid pattern and made Mongo fail the query (500).
            query["table_name"] = {"$regex": re.escape(search), "$options": "i"}
        return query

    @staticmethod
    def _to_object_id(metadata_id: str) -> ObjectId | None:
        try:
            return ObjectId(metadata_id)
        except (InvalidId, TypeError):
            return None
