from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import InvalidTokenError, Principal, verify_token
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


_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Bearer JWT. For local testing, mint one with `python scripts/mint_dev_token.py`.",
)


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> Principal:
    """Required on write routes (POST/PUT/DELETE) -- see app/api/routes/metadata.py.

    GET routes stay open on purpose: discovery is this catalog's whole
    point (docs/sdd-api-authentication.md, section 3). Overridden in tests
    via `app.dependency_overrides` -- same pattern as the repository.
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return verify_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


CurrentPrincipalDep = Annotated[Principal, Depends(get_current_principal)]
