import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.db import get_session
from app.log import JsonFormatter, request_id_var
from app.main import app
from tests.unit.conftest import ADMIN


def test_livez_needs_no_database():
    # No session override: a DB call here would try to reach localhost Postgres and fail.
    assert TestClient(app).get("/livez").json() == {"status": "ok"}


def test_request_id_is_echoed_or_generated(client):
    assert (
        client.get("/livez", headers={"X-Request-ID": "abc123"}).headers["X-Request-ID"] == "abc123"
    )
    assert len(client.get("/livez").headers["X-Request-ID"]) == 32


def test_metrics_use_route_templates_not_raw_paths(client):
    key = client.post("/devices", json={"name": "m"}, headers=ADMIN).json()
    client.get(
        f"/devices/{key['id']}/readings",
        params={"start": "2026-09-28T00:00:00Z", "end": "2026-09-28T01:00:00Z"},
        headers={"X-API-Key": key["api_key"]},
    )
    body = client.get("/metrics").text
    assert 'route="/devices/{device_id}/readings"' in body
    assert key["id"] not in body  # a raw id in a label would explode series cardinality


@pytest.fixture
def broken_db() -> Iterator[TestClient]:
    def unavailable() -> Iterator[None]:
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("db down"))
        yield

    app.dependency_overrides[get_session] = unavailable
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_database_outage_returns_503_with_retry_after(broken_db):
    r = broken_db.post(
        "/readings",
        json={"metric": "t", "value": 1, "ts": "2026-09-28T00:00:00Z"},
        headers={"X-API-Key": "tp_x"},
    )
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "5"
    assert "Traceback" not in r.text
    assert broken_db.get("/livez").status_code == 200


def test_settings_build_database_url_from_parts():
    s = Settings(
        db_host="db.internal", db_user="app", db_password="p@ss/word", db_sslmode="require"
    )
    assert s.database_url == (
        "postgresql+psycopg://app:p%40ss%2Fword@db.internal:5432/telemetry?sslmode=require"
    )


def test_production_refuses_the_dev_admin_token():
    with pytest.raises(ValidationError, match="ADMIN_TOKEN"):
        Settings(environment="production")
    assert Settings(environment="production", admin_token="x" * 32).admin_token == "x" * 32


def test_json_log_lines_carry_request_id_and_extra_fields():
    record = logging.makeLogRecord(
        {"name": "app", "levelname": "INFO", "msg": "request", "route": "/readings", "status": 201}
    )
    token = request_id_var.set("rid-1")
    try:
        entry = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert entry["msg"] == "request"
    assert entry["request_id"] == "rid-1"
    assert entry["route"] == "/readings"
    assert entry["status"] == 201
