from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.metadata import MetadataCreate

API = "/api/v1/metadata"


def test_health_check(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_metadata_returns_201(client: TestClient, sample_payload: MetadataCreate):
    response = client.post(API, json=sample_payload.model_dump(mode="json"))

    assert response.status_code == 201
    body = response.json()
    assert body["table_name"] == "orders"
    assert body["schema_version"] == 1
    assert "id" in body


def test_create_duplicate_returns_409(client: TestClient, sample_payload: MetadataCreate):
    payload = sample_payload.model_dump(mode="json")
    client.post(API, json=payload)

    response = client.post(API, json=payload)

    assert response.status_code == 409


def test_get_unknown_metadata_returns_404(client: TestClient):
    response = client.get(f"{API}/507f1f77bcf86cd799439011")

    assert response.status_code == 404


def test_full_crud_lifecycle(client: TestClient, sample_payload: MetadataCreate):
    create_response = client.post(API, json=sample_payload.model_dump(mode="json"))
    metadata_id = create_response.json()["id"]

    get_response = client.get(f"{API}/{metadata_id}")
    assert get_response.status_code == 200
    assert get_response.json()["table_name"] == "orders"

    list_response = client.get(API)
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    update_response = client.put(
        f"{API}/{metadata_id}",
        json={"description": "Now includes refunds", "updated_by": "henrique"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["description"] == "Now includes refunds"
    assert update_response.json()["schema_version"] == 1

    schema_change_response = client.put(
        f"{API}/{metadata_id}",
        json={
            "columns": [
                *sample_payload.model_dump(mode="json")["columns"],
                {"name": "discount", "data_type": "FLOAT64", "nullable": True, "is_pii": False},
            ],
            "updated_by": "henrique",
        },
    )
    assert schema_change_response.status_code == 200
    assert schema_change_response.json()["schema_version"] == 2

    history_response = client.get(f"{API}/{metadata_id}/schema-history")
    assert history_response.status_code == 200
    assert len(history_response.json()) == 2  # v1 (frozen) + current v2

    delete_response = client.delete(f"{API}/{metadata_id}")
    assert delete_response.status_code == 204

    get_after_delete = client.get(f"{API}/{metadata_id}")
    assert get_after_delete.status_code == 404


def test_create_metadata_sets_created_by_from_authenticated_principal(
    client: TestClient, sample_payload: MetadataCreate
):
    response = client.post(API, json=sample_payload.model_dump(mode="json"))

    # `sample_payload` sets created_by="henrique" in the request body, but
    # MetadataCreateRequest doesn't accept that field at all (see
    # app/models/metadata.py) -- it must come from the authenticated
    # principal (the `client` fixture's overridden test-user), never the
    # client-supplied body.
    assert response.json()["created_by"] == "test@example.com"


def test_create_metadata_without_token_returns_401(
    unauthenticated_client: TestClient, sample_payload: MetadataCreate
):
    response = unauthenticated_client.post(API, json=sample_payload.model_dump(mode="json"))

    assert response.status_code == 401


def test_update_metadata_without_token_returns_401(unauthenticated_client: TestClient):
    response = unauthenticated_client.put(f"{API}/507f1f77bcf86cd799439011", json={"description": "x"})

    assert response.status_code == 401


def test_delete_metadata_without_token_returns_401(unauthenticated_client: TestClient):
    response = unauthenticated_client.delete(f"{API}/507f1f77bcf86cd799439011")

    assert response.status_code == 401


def test_read_routes_do_not_require_a_token(unauthenticated_client: TestClient):
    # Discovery stays public on purpose -- see docs/sdd-api-authentication.md, section 3.
    list_response = unauthenticated_client.get(API)
    detail_response = unauthenticated_client.get(f"{API}/507f1f77bcf86cd799439011")

    assert list_response.status_code == 200
    assert detail_response.status_code == 404  # not 401: reached the handler, just not found


def test_list_supports_search_filter(client: TestClient, sample_payload: MetadataCreate):
    client.post(API, json=sample_payload.model_dump(mode="json"))
    other = sample_payload.model_dump(mode="json")
    other["table_name"] = "invoices"
    client.post(API, json=other)

    response = client.get(API, params={"search": "ord"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["table_name"] == "orders"
