"""HTTP boundary checks run without a database or provider connection."""

import httpx
import pytest
from catalogforge.main import app


@pytest.mark.parametrize("host", ["attacker.example", "localhost.attacker.example"])
async def test_untrusted_host_cannot_reach_login(host):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post(
            "/api/auth/login",
            headers={
                "host": host,
                "origin": f"http://{host}",
                "x-forwarded-host": "localhost",
                "forwarded": "host=localhost",
            },
            json={},
        )
    assert response.status_code == 400
    assert "Invalid host header" in response.text


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "localhost:8188"])
async def test_local_hosts_can_read_api_schema(host):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/api/openapi.json", headers={"host": host})
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "CatalogForge API"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


async def test_foreign_origin_cannot_write_to_local_host():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post(
            "/api/auth/login", headers={"origin": "https://attacker.example"}, json={}
        )
    assert response.status_code == 403


@pytest.mark.parametrize("length", ["invalid", "-1", "1.5"])
async def test_invalid_content_length_returns_client_error(length):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/api/openapi.json", headers={"content-length": length})
    assert response.status_code == 400
