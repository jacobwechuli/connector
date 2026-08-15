from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


def test_unauthorized_response_includes_cors_headers(monkeypatch):
    """CORS must wrap auth so browsers can see a real 401, not a CORS error."""
    monkeypatch.setenv("DASHBOARD_API_KEY", "test-dashboard-key")
    get_settings.cache_clear()
    try:
        response = TestClient(app).get(
            "/api/repositories", headers={"Origin": "http://localhost:3000"}
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_preflight_allows_configured_origin():
    response = TestClient(app).options(
        "/api/repositories",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
