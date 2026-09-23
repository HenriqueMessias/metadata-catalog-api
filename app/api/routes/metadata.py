from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentPrincipalDep, MetadataServiceDep
from app.core.config import get_settings
from app.models.metadata import (
    MetadataCreate,
    MetadataCreateRequest,
    MetadataResponse,
    MetadataUpdate,
    MetadataUpdateRequest,
    PaginatedResponse,
    SchemaVersionEntry,
)

router = APIRouter(prefix="/metadata", tags=["metadata"])


@router.post(
    "",
    response_model=MetadataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new table's metadata",
)
async def create_metadata(
    payload: MetadataCreateRequest, service: MetadataServiceDep, principal: CurrentPrincipalDep
) -> MetadataResponse:
    create = MetadataCreate(**payload.model_dump(), created_by=principal.email or principal.subject)
    metadata = await service.create(create)
    return MetadataResponse.model_validate(metadata.model_dump(by_alias=False))


@router.get(
    "",
    response_model=PaginatedResponse[MetadataResponse],
    summary="List/search table metadata",
)
async def list_metadata(
    service: MetadataServiceDep,
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1),
    owner_email: str | None = Query(default=None, description="Filter by owner's email"),
    domain: str | None = Query(default=None, description="Filter by business domain"),
    tag: str | None = Query(default=None, description="Filter by a single tag"),
    search: str | None = Query(default=None, description="Case-insensitive search on table name"),
) -> PaginatedResponse[MetadataResponse]:
    settings = get_settings()
    effective_limit = min(limit or settings.default_page_size, settings.max_page_size)
    items, total = await service.list(
        skip=skip,
        limit=effective_limit,
        owner_email=owner_email,
        domain=domain,
        tag=tag,
        search=search,
    )
    return PaginatedResponse(
        items=[MetadataResponse.model_validate(item.model_dump(by_alias=False)) for item in items],
        total=total,
        skip=skip,
        limit=effective_limit,
    )


@router.get(
    "/{metadata_id}",
    response_model=MetadataResponse,
    summary="Get the details of a single table's metadata",
)
async def get_metadata(metadata_id: str, service: MetadataServiceDep) -> MetadataResponse:
    metadata = await service.get(metadata_id)
    return MetadataResponse.model_validate(metadata.model_dump(by_alias=False))


@router.get(
    "/{metadata_id}/schema-history",
    response_model=list[SchemaVersionEntry],
    summary="List the schema evolution history of a table (past + current version)",
)
async def get_schema_history(metadata_id: str, service: MetadataServiceDep) -> list[SchemaVersionEntry]:
    metadata = await service.get(metadata_id)
    current_version = SchemaVersionEntry(
        version=metadata.schema_version,
        columns=metadata.columns,
        changed_at=metadata.updated_at,
        changed_by=metadata.updated_by,
    )
    return [*metadata.schema_history, current_version]


@router.put(
    "/{metadata_id}",
    response_model=MetadataResponse,
    summary="Update a table's metadata (schema changes bump schema_version)",
)
async def update_metadata(
    metadata_id: str,
    payload: MetadataUpdateRequest,
    service: MetadataServiceDep,
    principal: CurrentPrincipalDep,
) -> MetadataResponse:
    # exclude_unset=True is load-bearing: MetadataService.update() diffs
    # `columns` to decide whether to bump schema_version, so only fields
    # the client actually sent may be forwarded -- see the comment there.
    update = MetadataUpdate(
        **payload.model_dump(exclude_unset=True), updated_by=principal.email or principal.subject
    )
    metadata = await service.update(metadata_id, update)
    return MetadataResponse.model_validate(metadata.model_dump(by_alias=False))


@router.delete(
    "/{metadata_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a table's metadata from the catalog",
)
async def delete_metadata(metadata_id: str, service: MetadataServiceDep, principal: CurrentPrincipalDep) -> None:
    await service.delete(metadata_id)
