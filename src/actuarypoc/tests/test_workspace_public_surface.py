from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from actuarypoc.ui.server import app


def test_only_workspace_application_routes_are_public() -> None:
    application_paths = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path not in {"/", "/health", "/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}
    }

    assert application_paths
    assert all(path.startswith("/api/workspaces") for path in application_paths)
    assert "/api/products" not in application_paths
    assert "/api/run-detail" not in application_paths


def test_root_redirects_to_workspace_ui() -> None:
    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/web"
