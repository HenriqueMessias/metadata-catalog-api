"""The emulator's HTTP client sends the Bearer token the API's write routes
require. Uses `httpx.MockTransport`: no network, no running API.
"""

import httpx

from scripts.glue_emulator.cli import _build_parser
from scripts.glue_emulator.sync import CatalogSyncClient, SyncStats

GLUE_TABLE = {
    "DatabaseName": "sales",
    "Name": "orders",
    "StorageDescriptor": {"Columns": [{"Name": "id", "Type": "string"}], "Location": "s3://b/orders"},
    "Parameters": {"owner_email": "o@example.com", "owner_name": "Owner"},
}


def _recording_transport(seen: list[httpx.Request], post_status: int = 201):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(post_status, json={})

    return httpx.MockTransport(handler)


def test_token_is_sent_as_bearer_on_every_request():
    seen: list[httpx.Request] = []
    with CatalogSyncClient("http://api/api/v1", token="abc", transport=_recording_transport(seen)) as client:
        stats = SyncStats()
        client.sync_table(GLUE_TABLE, stats)

    assert stats.created == 1
    assert [r.method for r in seen] == ["GET", "POST"]
    assert all(r.headers["authorization"] == "Bearer abc" for r in seen)


def test_no_token_sends_no_authorization_header():
    seen: list[httpx.Request] = []
    with CatalogSyncClient("http://api/api/v1", transport=_recording_transport(seen)) as client:
        client.sync_table(GLUE_TABLE, SyncStats())

    assert all("authorization" not in r.headers for r in seen)


def test_unauthorized_write_is_counted_as_failure_with_status_in_error():
    seen: list[httpx.Request] = []
    with CatalogSyncClient("http://api/api/v1", transport=_recording_transport(seen, post_status=401)) as client:
        stats = SyncStats()
        client.sync_table(GLUE_TABLE, stats)

    assert stats.failed == 1 and stats.created == 0
    assert ": 401 " in stats.errors[0]  # what the CLI's token hint keys on


def test_cli_token_defaults_to_env_var(monkeypatch):
    monkeypatch.setenv("CATALOG_API_TOKEN", "from-env")
    assert _build_parser().parse_args(["seed"]).token == "from-env"
    assert _build_parser().parse_args(["seed", "--token", "explicit"]).token == "explicit"

    monkeypatch.delenv("CATALOG_API_TOKEN")
    assert _build_parser().parse_args(["seed"]).token is None
