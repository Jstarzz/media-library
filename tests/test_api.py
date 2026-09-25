from fastapi.testclient import TestClient

from app.main import app


def test_health_and_auth():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/workspaces").status_code == 401
        response = client.post("/api/v1/workspaces", headers={"Authorization":"Bearer test-admin"}, json={"slug":"dte","name":"DTE"})
        assert response.status_code == 201
        listing = client.get("/api/v1/workspaces", headers={"Authorization":"Bearer test-admin"})
        assert listing.json() == [{"slug":"dte","name":"DTE"}]
