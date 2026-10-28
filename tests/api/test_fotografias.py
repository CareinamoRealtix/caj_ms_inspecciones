import uuid
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.application.inspeccion_service import InspeccionService
from app.main import app
from app.presentation.api.dependencies.inspecciones import get_inspeccion_service

_INSPECCION_ID = "00000000-0000-4000-8000-000000000501"


class FotografiasRepository:
    def __init__(self, lifecycle: dict[str, Any] | None, fotos: list[dict[str, Any]]) -> None:
        self._lifecycle = lifecycle
        self._fotos = fotos

    async def get_inspeccion_lifecycle(self, id_inspeccion: uuid.UUID) -> dict[str, Any] | None:
        return self._lifecycle

    async def get_fotografias_by_inspeccion(
        self, id_inspeccion: uuid.UUID
    ) -> list[dict[str, Any]]:
        return self._fotos


def _foto(**overrides: Any) -> dict[str, Any]:
    base = {
        "id_fotografia": uuid.uuid4(),
        "url_s3": "https://via.placeholder.com/300",
        "nombre_archivo": "fachada.jpg",
        "es_visible_geovisor": True,
        "es_foto_principal": True,
        "orden": 0,
    }
    base.update(overrides)
    return base


async def test_get_fotografias_retorna_id_inspeccion_y_arreglo() -> None:
    repo = FotografiasRepository(
        lifecycle={"activa": False, "fecha_realizada": "2026-09-08"},
        fotos=[_foto()],
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/v1/inspeccion/{_INSPECCION_ID}/fotografias")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["id_inspeccion"] == _INSPECCION_ID
    assert set(body.keys()) == {"id_inspeccion", "fotografias"}
    assert len(body["fotografias"]) == 1
    assert body["fotografias"][0]["url_s3"] == "https://via.placeholder.com/300"
    assert body["fotografias"][0]["es_foto_principal"] is True


async def test_get_fotografias_vacio_si_la_inspeccion_no_tiene_fotos() -> None:
    repo = FotografiasRepository(
        lifecycle={"activa": True, "fecha_realizada": None},
        fotos=[],
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/v1/inspeccion/{_INSPECCION_ID}/fotografias")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["fotografias"] == []


async def test_get_fotografias_responde_404_si_la_inspeccion_no_existe() -> None:
    repo = FotografiasRepository(lifecycle=None, fotos=[])
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/v1/inspeccion/{_INSPECCION_ID}/fotografias")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


class _FirmadorFalso:
    def firmar_foto(self, referencia: str) -> str:
        return f"https://cdn.test/{referencia}?Expires=1&Signature=s&Key-Pair-Id=K"


async def test_get_fotografias_firma_la_clave_guardada_en_la_bd() -> None:
    repo = FotografiasRepository(
        lifecycle={"activa": False, "fecha_realizada": "2026-09-08"},
        fotos=[_foto(url_s3="fotos/a/b/0001.jpg")],
    )
    service = InspeccionService(repo=repo, fotos_signer=_FirmadorFalso())  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/v1/inspeccion/{_INSPECCION_ID}/fotografias")
    finally:
        app.dependency_overrides.clear()

    assert response.json()["fotografias"][0]["url_s3"] == (
        "https://cdn.test/fotos/a/b/0001.jpg?Expires=1&Signature=s&Key-Pair-Id=K"
    )
