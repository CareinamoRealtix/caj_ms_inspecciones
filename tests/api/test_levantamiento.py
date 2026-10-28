import uuid
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.application.inspeccion_service import InspeccionService
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.database.inspeccion_repository import LevantamientoFinalizeResult
from app.main import app
from app.presentation.api.dependencies.inspecciones import get_inspeccion_service

_INSPECCION_ID = "00000000-0000-4000-8000-000000000401"
_ID_LEVANTAMIENTO = "00000000-0000-4000-8000-000000000402"


class LevantamientoRepository:
    def __init__(self, resultado: LevantamientoFinalizeResult) -> None:
        self.resultado = resultado
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
        return self.resultado


def _payload() -> dict[str, Any]:
    return {
        "id_operacion": str(uuid.uuid4()),
        "condicion_bien": "BUENA",
        "estado_ocupacion": "DESOCUPADO",
        "fecha_levantamiento": "2026-09-08",
    }


def _override_flag(*, habilitado: bool) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[call-arg]
        _env_file=None, enable_direct_levantamiento_endpoint=habilitado
    )


async def test_finalizar_levantamiento_crea_y_responde_201() -> None:
    repo = LevantamientoRepository(
        LevantamientoFinalizeResult(estado="creado", id_levantamiento=uuid.UUID(_ID_LEVANTAMIENTO))
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/v1/inspeccion/{_INSPECCION_ID}/levantamiento",
                headers={"X-User-Email": "inspector@example.com"},
                json=_payload(),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["id_levantamiento"] == _ID_LEVANTAMIENTO


async def test_finalizar_levantamiento_reintento_identico_responde_200() -> None:
    respuesta_previa = {
        "id_levantamiento": _ID_LEVANTAMIENTO,
        "id_inspeccion": _INSPECCION_ID,
        "estado_inspeccion": "Finalizada",
        "mensaje": "Levantamiento finalizado correctamente",
    }
    repo = LevantamientoRepository(
        LevantamientoFinalizeResult(estado="repetido", respuesta_previa=respuesta_previa)
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/v1/inspeccion/{_INSPECCION_ID}/levantamiento",
                headers={"X-User-Email": "inspector@example.com"},
                json=_payload(),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


async def test_finalizar_levantamiento_inspeccion_no_encontrada_responde_404() -> None:
    repo = LevantamientoRepository(LevantamientoFinalizeResult(estado="no_encontrada"))
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/v1/inspeccion/{_INSPECCION_ID}/levantamiento",
                headers={"X-User-Email": "inspector@example.com"},
                json=_payload(),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_finalizar_levantamiento_conflicto_responde_409() -> None:
    repo = LevantamientoRepository(LevantamientoFinalizeResult(estado="ya_finalizada"))
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/v1/inspeccion/{_INSPECCION_ID}/levantamiento",
                headers={"X-User-Email": "inspector@example.com"},
                json=_payload(),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409


async def test_finalizar_levantamiento_codigo_invalido_responde_422() -> None:
    repo = LevantamientoRepository(
        LevantamientoFinalizeResult(estado="creado", id_levantamiento=uuid.UUID(_ID_LEVANTAMIENTO))
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=True)
    payload = _payload()
    payload["condicion_bien"] = "INEXISTENTE"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/v1/inspeccion/{_INSPECCION_ID}/levantamiento",
                headers={"X-User-Email": "inspector@example.com"},
                json=payload,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert repo.finalizar_calls == []


async def test_finalizar_levantamiento_responde_404_con_flag_deshabilitado() -> None:
    repo = LevantamientoRepository(
        LevantamientoFinalizeResult(estado="creado", id_levantamiento=uuid.UUID(_ID_LEVANTAMIENTO))
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    _override_flag(habilitado=False)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/v1/inspeccion/{_INSPECCION_ID}/levantamiento",
                headers={"X-User-Email": "inspector@example.com"},
                json=_payload(),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert repo.finalizar_calls == []
