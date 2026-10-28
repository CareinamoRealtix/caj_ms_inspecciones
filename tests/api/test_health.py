from httpx import ASGITransport, AsyncClient

from app.infrastructure.database.connection import DatabaseUnavailableError
from app.main import app
from app.presentation.api.dependencies.database import get_database


class ReadyDatabase:
    async def ping(self) -> None:
        return None


class UnavailableDatabase:
    async def ping(self) -> None:
        raise DatabaseUnavailableError


async def test_health_returns_service_status() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/inspeccion/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ms-inspecciones"}
    assert response.headers["X-Request-ID"]


async def test_cors_allows_any_origin_method_and_headers() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/v1/inspeccion/health",
            headers={
                "Origin": "https://frontend.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]
    assert "authorization" in response.headers["Access-Control-Allow-Headers"].lower()


async def test_ready_when_database_is_available() -> None:
    app.dependency_overrides[get_database] = lambda: ReadyDatabase()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/inspeccion/ready", headers={"X-Request-ID": "test-request"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers["X-Request-ID"] == "test-request"


async def test_ready_hides_database_error_details() -> None:
    app.dependency_overrides[get_database] = lambda: UnavailableDatabase()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/inspeccion/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert "postgres" not in response.text.lower()
