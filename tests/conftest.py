from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_principal, get_metadata_repository
from app.core.security import Principal
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
def principal() -> Principal:
    return Principal(subject="test-user", email="test@example.com")


@pytest.fixture
def client(repository: InMemoryMetadataRepository, principal: Principal) -> TestClient:
    @asynccontextmanager
    async def noop_lifespan(app):
        # No real MongoDB connection needed: the repository dependency is
        # overridden below to use the in-memory fake instead.
        yield

    app = create_app(lifespan_context=noop_lifespan)
    app.dependency_overrides[get_metadata_repository] = lambda: repository
    # Same pattern as the repository: bypass real JWT verification in tests
    # via FastAPI's dependency_overrides, so tests stay hermetic (no key
    # files, no network) -- see tests/test_auth.py for the one test that
    # exercises get_current_principal itself, without this override.
    app.dependency_overrides[get_current_principal] = lambda: principal

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def unauthenticated_client(repository: InMemoryMetadataRepository) -> TestClient:
    """Like `client`, but does NOT override auth -- for testing the 401 path."""

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = create_app(lifespan_context=noop_lifespan)
    app.dependency_overrides[get_metadata_repository] = lambda: repository

    with TestClient(app) as test_client:
        yield test_client
