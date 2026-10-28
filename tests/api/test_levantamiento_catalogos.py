from typing import Any

from httpx import ASGITransport, AsyncClient

from app.application.inspeccion_service import InspeccionService
from app.infrastructure.config.settings import Settings, get_settings
from app.main import app
from app.presentation.api.dependencies.inspecciones import get_inspeccion_service


class LevantamientoCatalogRepository:
    async def get_levantamiento_opciones_activas(self) -> list[dict[str, Any]]:
        return [
            {
                "tipo_catalogo": "PUERTA_MATERIAL",
                "codigo": "MADERA",
                "nombre": "Madera",
                "requiere_cantidad": True,
                "permite_descripcion": False,
                "orden": 3,
            },
            {
                "tipo_catalogo": "PUERTA_MATERIAL",
                "codigo": "HIERRO",
                "nombre": "Hierro",
                "requiere_cantidad": True,
                "permite_descripcion": False,
                "orden": 1,
            },
            {
                "tipo_catalogo": "CONDICION_BIEN",
                "codigo": "BUENA",
                "nombre": "Buena",
                "requiere_cantidad": False,
                "permite_descripcion": False,
                "orden": 1,
            },
        ]


async def test_catalogos_levantamiento_agrupa_por_tipo_catalogo_y_respeta_orden() -> None:
    service = InspeccionService(repo=LevantamientoCatalogRepository())  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/inspeccion/levantamiento/catalogos")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert set(body["catalogos"].keys()) == {"PUERTA_MATERIAL", "CONDICION_BIEN"}
    codigos_puertas = [item["codigo"] for item in body["catalogos"]["PUERTA_MATERIAL"]]
    assert codigos_puertas == ["MADERA", "HIERRO"]
    assert "version" in body


async def test_catalogos_levantamiento_disponible_con_flag_directo_deshabilitado() -> None:
    service = InspeccionService(repo=LevantamientoCatalogRepository())  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[call-arg]
        _env_file=None, enable_direct_levantamiento_endpoint=False
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/inspeccion/levantamiento/catalogos")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
