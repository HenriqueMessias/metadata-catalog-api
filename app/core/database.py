from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings


class MongoDatabase:
    """Thin wrapper around the Motor client lifecycle.

    Kept separate from FastAPI's app object so it can be created/torn down
    explicitly in the lifespan handler and swapped out easily in tests.
    """

    client: AsyncIOMotorClient | None = None
    database: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        settings = get_settings()
        self.client = AsyncIOMotorClient(settings.mongo_uri)
        self.database = self.client[settings.mongo_db_name]
        await self._ensure_indexes()

    async def disconnect(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
            self.database = None

    async def _ensure_indexes(self) -> None:
        settings = get_settings()
        collection = self.database[settings.mongo_collection]
        # A table is uniquely identified by where it lives, not just its name.
        await collection.create_index(
            [("database_name", 1), ("schema_name", 1), ("table_name", 1)],
            unique=True,
            name="uq_table_identity",
        )
        await collection.create_index("owner.email", name="ix_owner_email")
        await collection.create_index("tags", name="ix_tags")


mongo_database = MongoDatabase()
