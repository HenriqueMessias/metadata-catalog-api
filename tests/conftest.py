from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_metadata_repository
from app.main import create_app
from app.models.metadata import ColumnSchema, MetadataCreate, Owner
from app.services.metadata_service import MetadataService
from tests.fakes import InMemoryMetadataRepository


@pytest.fixture
def repository() -> InMemoryMetadataRepository:
    return InMemoryMetadataRepository()


@pytest.fixture
def service(repository: InMemoryMetadataRepository) -> MetadataService:
    return MetadataService(repository)


@pytest.fixture
def sample_payload() -> MetadataCreate:
    return MetadataCreate(
        table_name="orders",
        database_name="sales",
        schema_name="public",
        description="Fact table with one row per customer order.",
        owner=Owner(name="Henrique Messias", email="henrique@example.com", team="Data Platform"),
        domain="sales",
        tags=["fact", "core"],
        columns=[
            ColumnSchema(name="order_id", data_type="STRING", nullable=False),
            ColumnSchema(name="customer_id", data_type="STRING", nullable=False),
            ColumnSchema(name="amount", data_type="FLOAT64", nullable=False),
        ],
        location="project.sales.orders",
        created_by="henrique",
    )


@pytest.fixture
def client(repository: InMemoryMetadataRepository) -> TestClient:
    @asynccontextmanager
    async def noop_lifespan(app):
        # No real MongoDB connection needed: the repository dependency is
        # overridden below to use the in-memory fake instead.
        yield

    app = create_app(lifespan_context=noop_lifespan)
    app.dependency_overrides[get_metadata_repository] = lambda: repository

    with TestClient(app) as test_client:
        yield test_client
