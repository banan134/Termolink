import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_returns_ok(client: Client) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": True, "worker": None, "backup": None}


@pytest.mark.django_db
def test_openapi_schema_is_served(client: Client) -> None:
    response = client.get("/api/schema/")
    assert response.status_code == 200
    assert b"/api/v1/health" in response.content
