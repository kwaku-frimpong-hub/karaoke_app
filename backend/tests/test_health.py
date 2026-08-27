"""Tests for the health endpoints."""

from fastapi.testclient import TestClient

from app.schemas.health import SERVICE_NAME


def test_root_returns_service_identity(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "service": SERVICE_NAME,
        "status": "ok",
        "version": "0.1.0",
    }


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == SERVICE_NAME
    assert response.json()["status"] == "ok"


def test_health_ready_reports_database_ok(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"] == {"database": "ok"}
