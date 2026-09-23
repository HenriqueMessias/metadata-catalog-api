from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.repositories.base import MetadataRepository
from app.repositories.mongo_repository import MongoMetadataRepository
from app.services.metadata_service import MetadataService


def get_metadata_repository(request: Request) -> MetadataRepository:
    """Resolve the repository implementation for the current request.

    Reads the live Mongo collection off `app.state`, set during the
    lifespan handler in `main.py`. Overridden in tests to return an
    in-memory fake instead (see tests/conftest.py).
    """
    collection = request.app.state.metadata_collection
    return MongoMetadataRepository(collection)


def get_metadata_service(
    repository: Annotated[MetadataRepository, Depends(get_metadata_repository)],
) -> MetadataService:
    return MetadataService(repository)


MetadataServiceDep = Annotated[MetadataService, Depends(get_metadata_service)]
