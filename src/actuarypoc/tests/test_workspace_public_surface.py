from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from actuarypoc.ui.server import app


def test_only_workspace_application_routes_are_public() -> None:
    supported_diagnostic_paths = {"/ui/dev", "/api/dev/objects", "/api/dev/object"}
    application_paths = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path
        not in {
            "/",
            "/health",
            "/docs",
            "/docs/oauth2-redirect",
            "/openapi.json",
            "/redoc",
            *supported_diagnostic_paths,
        }
    }

    assert application_paths
    assert all(path.startswith("/api/workspaces") for path in application_paths)
    assert supported_diagnostic_paths.issubset({route.path for route in app.routes})
    assert "/api/products" not in application_paths
    assert "/api/run-detail" not in application_paths


def test_workspace_supports_additional_documents_and_analysis_reruns() -> None:
    route_methods = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert ("/api/workspaces/{workspace_id}/documents", "POST") in route_methods
    assert ("/api/workspaces/{workspace_id}/analyze", "POST") in route_methods
    assert ("/api/workspaces/{workspace_id}/projection-graph", "GET") in route_methods
    assert ("/api/workspaces/{workspace_id}/filed-mechanics/accept", "POST") in route_methods
    assert ("/api/workspaces/{workspace_id}/synthetic-coi/preview", "POST") in route_methods
    assert ("/api/workspaces/{workspace_id}/synthetic-coi/accept", "POST") in route_methods
    assert ("/api/workspaces/{workspace_id}/synthetic-coi", "DELETE") in route_methods
    assert ("/api/workspaces/{workspace_id}/synthetic-surrender/preview", "POST") in route_methods
    assert ("/api/workspaces/{workspace_id}/synthetic-surrender/accept", "POST") in route_methods
    assert ("/api/workspaces/{workspace_id}/synthetic-surrender", "DELETE") in route_methods


def test_root_redirects_to_workspace_ui() -> None:
    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/web"
