from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.routes.metadata import router as metadata_router
from app.core.config import get_settings
from app.core.database import mongo_database
from app.exceptions import DuplicateMetadataError, MetadataNotFoundError


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await mongo_database.connect()
    app.state.metadata_collection = mongo_database.database[settings.mongo_collection]
    yield
    await mongo_database.disconnect()


def create_app(lifespan_context=lifespan) -> FastAPI:
    """Build the FastAPI app.

    `lifespan_context` is injectable so tests can swap in a no-op lifespan
    and avoid connecting to a real MongoDB instance (see tests/conftest.py).
    """
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Catalog service for discovering, understanding and governing data tables.",
        version="1.0.0",
        lifespan=lifespan_context,
    )

    app.include_router(metadata_router, prefix=settings.api_prefix)

    @app.exception_handler(MetadataNotFoundError)
    async def not_found_handler(request: Request, exc: MetadataNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})

    @app.exception_handler(DuplicateMetadataError)
    async def duplicate_handler(request: Request, exc: DuplicateMetadataError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})

    @app.get("/health", tags=["health"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
