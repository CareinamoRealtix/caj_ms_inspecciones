import uuid
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.application.inspeccion_service import InspeccionService
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.database.inspeccion_repository import LevantamientoFinalizeResult
from app.main import app
from app.presentation.api.dependencies.inspecciones import get_inspeccion_service

_INSPECCION_ID_1 = "00000000-0000-4000-8000-000000000501"
_INSPECCION_ID_2 = "00000000-0000-4000-8000-000000000502"
_ID_LEVANTAMIENTO_1 = "00000000-0000-4000-8000-000000000601"
_ID_LEVANTAMIENTO_2 = "00000000-0000-4000-8000-000000000602"


class LevantamientoBatchRepository:
    def __init__(self, resultados: dict[str, LevantamientoFinalizeResult]) -> None:
        self.resultados = resultados
        self.finalizar_calls: list[dict[str, Any]] = []

    async def get_levantamiento_opciones_activas(self) -> list[dict[str, Any]]:
        return [
            {
                "tipo_catalogo": "CONDICION_BIEN",
                "codigo": "BUENA",
                "nombre": "Buena",
                "requiere_cantidad": False,
                "permite_descripcion": False,
                "orden": 1,
            },
            {
                "tipo_catalogo": "ESTADO_OCUPACION",
                "codigo": "DESOCUPADO",
                "nombre": "Desocupado",
                "requiere_cantidad": False,
                "permite_descripcion": False,
                "orden": 1,
            },
        ]

    async def finalizar_levantamiento(self, **kwargs: Any) -> LevantamientoFinalizeResult:
        self.finalizar_calls.append(kwargs)
        return self.resultados[str(kwargs["id_inspeccion"])]


def _item(id_inspeccion: str, *, id_operacion: str | None = None) -> dict[str, Any]:
    return {
        "id_inspeccion": id_inspeccion,
        "id_operacion": id_operacion or str(uuid.uuid4()),
        "condicion_bien": "BUENA",
        "estado_ocupacion": "DESOCUPADO",
        "fecha_levantamiento": "2026-09-08",
    }


def _override_flag(*, habilitado: bool) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[call-arg]
        _env_file=None, enable_direct_levantamiento_endpoint=habilitado
    )


async def test_batch_procesa_varias_inspecciones_exitosamente() -> None:
    repo = LevantamientoBatchRepository(
        {
            _INSPECCION_ID_1: LevantamientoFinalizeResult(
                estado="creado", id_levantamiento=uuid.UUID(_ID_LEVANTAMIENTO_1)
            ),
            _INSPECCION_ID_2: LevantamientoFinalizeResult(
                estado="creado", id_levantamiento=uuid.UUID(_ID_LEVANTAMIENTO_2)
            ),
        }
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/levantamiento/batch",
                headers={"X-User-Email": "inspector@example.com"},
                json={"levantamientos": [_item(_INSPECCION_ID_1), _item(_INSPECCION_ID_2)]},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["exitosos"] == 2
    assert body["fallidos"] == 0
    resultados_por_id = {r["id_inspeccion"]: r for r in body["resultados"]}
    assert resultados_por_id[_INSPECCION_ID_1]["exito"] is True
    assert resultados_por_id[_INSPECCION_ID_1]["id_levantamiento"] == _ID_LEVANTAMIENTO_1
    assert resultados_por_id[_INSPECCION_ID_2]["exito"] is True
    assert resultados_por_id[_INSPECCION_ID_2]["id_levantamiento"] == _ID_LEVANTAMIENTO_2
    assert len(repo.finalizar_calls) == 2


async def test_batch_continua_cuando_un_item_falla() -> None:
    repo = LevantamientoBatchRepository(
        {
            _INSPECCION_ID_1: LevantamientoFinalizeResult(
                estado="creado", id_levantamiento=uuid.UUID(_ID_LEVANTAMIENTO_1)
            ),
            _INSPECCION_ID_2: LevantamientoFinalizeResult(estado="no_encontrada"),
        }
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/levantamiento/batch",
                headers={"X-User-Email": "inspector@example.com"},
                json={"levantamientos": [_item(_INSPECCION_ID_1), _item(_INSPECCION_ID_2)]},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["exitosos"] == 1
    assert body["fallidos"] == 1
    resultados_por_id = {r["id_inspeccion"]: r for r in body["resultados"]}
    assert resultados_por_id[_INSPECCION_ID_1]["exito"] is True
    assert resultados_por_id[_INSPECCION_ID_2]["exito"] is False
    assert resultados_por_id[_INSPECCION_ID_2]["codigo_error"] == "no_encontrada"
    # Ambos ítems se intentan aunque el primero se procese antes que el que falla.
    assert len(repo.finalizar_calls) == 2


async def test_batch_reintento_identico_se_reporta_como_repetido() -> None:
    respuesta_previa = {
        "id_levantamiento": _ID_LEVANTAMIENTO_1,
        "id_inspeccion": _INSPECCION_ID_1,
        "estado_inspeccion": "Finalizada",
        "mensaje": "Levantamiento finalizado correctamente",
    }
    repo = LevantamientoBatchRepository(
        {
            _INSPECCION_ID_1: LevantamientoFinalizeResult(
                estado="repetido", respuesta_previa=respuesta_previa
            ),
        }
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/levantamiento/batch",
                headers={"X-User-Email": "inspector@example.com"},
                json={"levantamientos": [_item(_INSPECCION_ID_1)]},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    resultado = response.json()["resultados"][0]
    assert resultado["exito"] is True
    assert resultado["repetido"] is True


async def test_batch_rechaza_id_inspeccion_duplicado_en_el_lote() -> None:
    repo = LevantamientoBatchRepository({})
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/levantamiento/batch",
                headers={"X-User-Email": "inspector@example.com"},
                json={
                    "levantamientos": [
                        _item(_INSPECCION_ID_1),
                        _item(_INSPECCION_ID_1),
                    ]
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_batch_responde_404_con_flag_deshabilitado() -> None:
    _override_flag(habilitado=False)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/levantamiento/batch",
                headers={"X-User-Email": "inspector@example.com"},
                json={"levantamientos": [_item(_INSPECCION_ID_1)]},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
