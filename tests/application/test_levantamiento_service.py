import uuid
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from app.application.inspeccion_service import (
    CodigoCatalogoInvalidoError,
    InspeccionNotFoundError,
    InspeccionService,
    LevantamientoOperacionConflictoError,
)
from app.infrastructure.clients.ordenes_servicio_client import OrdenesServicioWebhookError
from app.infrastructure.database.inspeccion_repository import LevantamientoFinalizeResult
from app.presentation.api.schemas.inspecciones import LevantamientoRequest

_INSPECCION_ID = uuid.UUID("00000000-0000-4000-8000-000000000301")
_ID_LEVANTAMIENTO = uuid.UUID("00000000-0000-4000-8000-000000000302")


_CATALOGO_BASE: list[dict[str, Any]] = [
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

_CATALOGO_SERVICIOS_REQUERIDOS: list[dict[str, Any]] = [
    {
        "tipo_catalogo": "LIMPIEZA",
        "codigo": "RETIRO_ENSERES",
        "nombre": "Retiro de enseres",
        "requiere_cantidad": False,
        "permite_descripcion": False,
        "orden": 3,
    },
    {
        "tipo_catalogo": "CERRAJERIA_MATERIAL",
        "codigo": "HIERRO",
        "nombre": "Hierro",
        "requiere_cantidad": True,
        "permite_descripcion": False,
        "orden": 1,
    },
    {
        "tipo_catalogo": "INSPECCION_TECNICA",
        "codigo": "ELECTRICA",
        "nombre": "Inspección eléctrica",
        "requiere_cantidad": False,
        "permite_descripcion": False,
        "orden": 1,
    },
]


class LevantamientoServiceRepository:
    def __init__(
        self,
        resultado: LevantamientoFinalizeResult,
        catalogo: list[dict[str, Any]] | None = None,
    ) -> None:
        self.resultado = resultado
        self.finalizar_calls: list[dict[str, Any]] = []
        self._catalogo = catalogo if catalogo is not None else _CATALOGO_BASE

    async def get_levantamiento_opciones_activas(self) -> list[dict[str, Any]]:
        return self._catalogo

    async def finalizar_levantamiento(self, **kwargs: Any) -> LevantamientoFinalizeResult:
        self.finalizar_calls.append(kwargs)
        return self.resultado


class FakeOrdenesServicioClient:
    def __init__(self, *, falla: bool = False) -> None:
        self.falla = falla
        self.payloads: list[dict[str, Any]] = []

    async def notificar_servicios_requeridos(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)
        if self.falla:
            raise OrdenesServicioWebhookError("boom")


def _body() -> LevantamientoRequest:
    return LevantamientoRequest(
        id_operacion=uuid.uuid4(),
        condicion_bien="BUENA",
        estado_ocupacion="DESOCUPADO",
        fecha_levantamiento=date(2026, 9, 8),
    )


async def test_finalizar_levantamiento_creado() -> None:
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(estado="creado", id_levantamiento=_ID_LEVANTAMIENTO)
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]

    respuesta, repetido = await service.finalizar_levantamiento(
        _INSPECCION_ID, _body(), usuario="inspector@example.com"
    )

    assert repetido is False
    assert respuesta.id_levantamiento == _ID_LEVANTAMIENTO
    assert respuesta.estado_inspeccion == "Finalizada"
    assert len(repo.finalizar_calls) == 1


async def test_finalizar_levantamiento_repetido_reconstruye_respuesta_previa() -> None:
    respuesta_previa = {
        "id_levantamiento": str(_ID_LEVANTAMIENTO),
        "id_inspeccion": str(_INSPECCION_ID),
        "estado_inspeccion": "Finalizada",
        "mensaje": "Levantamiento finalizado correctamente",
    }
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(estado="repetido", respuesta_previa=respuesta_previa)
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]

    respuesta, repetido = await service.finalizar_levantamiento(
        _INSPECCION_ID, _body(), usuario="inspector@example.com"
    )

    assert repetido is True
    assert respuesta.id_levantamiento == _ID_LEVANTAMIENTO


async def test_finalizar_levantamiento_inspeccion_no_encontrada() -> None:
    repo = LevantamientoServiceRepository(LevantamientoFinalizeResult(estado="no_encontrada"))
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]

    with pytest.raises(InspeccionNotFoundError):
        await service.finalizar_levantamiento(_INSPECCION_ID, _body(), usuario="inspector@ej.com")


async def test_finalizar_levantamiento_conflicto_contenido() -> None:
    repo = LevantamientoServiceRepository(LevantamientoFinalizeResult(estado="conflicto_contenido"))
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]

    with pytest.raises(LevantamientoOperacionConflictoError) as excinfo:
        await service.finalizar_levantamiento(_INSPECCION_ID, _body(), usuario="inspector@ej.com")

    assert excinfo.value.motivo == "contenido_diferente"


async def test_finalizar_levantamiento_ya_finalizada() -> None:
    repo = LevantamientoServiceRepository(LevantamientoFinalizeResult(estado="ya_finalizada"))
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]

    with pytest.raises(LevantamientoOperacionConflictoError) as excinfo:
        await service.finalizar_levantamiento(_INSPECCION_ID, _body(), usuario="inspector@ej.com")

    assert excinfo.value.motivo == "ya_finalizada"


async def test_finalizar_levantamiento_rechaza_id_operacion_reutilizado_de_otra_inspeccion() -> (
    None
):
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(estado="operacion_de_otra_inspeccion")
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]

    with pytest.raises(LevantamientoOperacionConflictoError) as excinfo:
        await service.finalizar_levantamiento(_INSPECCION_ID, _body(), usuario="inspector@ej.com")

    assert excinfo.value.motivo == "otra_inspeccion"


async def test_finalizar_levantamiento_rechaza_codigo_invalido_sin_llamar_al_repositorio() -> None:
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(estado="creado", id_levantamiento=_ID_LEVANTAMIENTO)
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    body = LevantamientoRequest(
        id_operacion=uuid.uuid4(),
        condicion_bien="INEXISTENTE",
        estado_ocupacion="DESOCUPADO",
        fecha_levantamiento=date(2026, 9, 8),
    )

    with pytest.raises(CodigoCatalogoInvalidoError):
        await service.finalizar_levantamiento(_INSPECCION_ID, body, usuario="inspector@example.com")

    assert repo.finalizar_calls == []


async def test_finalizar_levantamiento_pasa_fotografias_al_repositorio() -> None:
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(estado="creado", id_levantamiento=_ID_LEVANTAMIENTO)
    )
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]
    body = LevantamientoRequest(
        id_operacion=uuid.uuid4(),
        condicion_bien="BUENA",
        estado_ocupacion="DESOCUPADO",
        fecha_levantamiento=date(2026, 9, 8),
        fotografias=[
            {"url": "https://via.placeholder.com/300", "es_foto_principal": True},
            {"url": "https://via.placeholder.com/400", "nombre_archivo": "fachada.jpg"},
        ],
    )

    await service.finalizar_levantamiento(_INSPECCION_ID, body, usuario="inspector@example.com")

    fotografias_enviadas = repo.finalizar_calls[0]["fotografias"]
    assert fotografias_enviadas[0]["url"] == "https://via.placeholder.com/300"
    assert fotografias_enviadas[0]["es_foto_principal"] is True
    assert fotografias_enviadas[1]["nombre_archivo"] == "fachada.jpg"
    assert "fotografias" not in repo.finalizar_calls[0]["data"]


def test_levantamiento_request_rechaza_url_de_fotografia_sin_esquema_http() -> None:
    with pytest.raises(ValidationError):
        LevantamientoRequest(
            id_operacion=uuid.uuid4(),
            condicion_bien="BUENA",
            estado_ocupacion="DESOCUPADO",
            fecha_levantamiento=date(2026, 9, 8),
            fotografias=[{"url": "ftp://placeholder.com/foto.png"}],
        )


def test_levantamiento_request_rechaza_mas_de_una_foto_principal() -> None:
    with pytest.raises(ValidationError):
        LevantamientoRequest(
            id_operacion=uuid.uuid4(),
            condicion_bien="BUENA",
            estado_ocupacion="DESOCUPADO",
            fecha_levantamiento=date(2026, 9, 8),
            fotografias=[
                {"url": "https://via.placeholder.com/300", "es_foto_principal": True},
                {"url": "https://via.placeholder.com/400", "es_foto_principal": True},
            ],
        )


# ------------------------------------------------------------------
# Webhook a ms-requerimientos (órdenes de servicio)
# ------------------------------------------------------------------

_ID_BIEN_INVENTARIO = uuid.UUID("00000000-0000-4000-8000-000000000303")


def _body_con_servicios_requeridos() -> LevantamientoRequest:
    return LevantamientoRequest(
        id_operacion=uuid.uuid4(),
        condicion_bien="BUENA",
        estado_ocupacion="DESOCUPADO",
        coordenadas="9.3405,-82.2500",
        servicios_requeridos={
            "LIMPIEZA": [{"codigo": "RETIRO_ENSERES"}],
            "CERRAJERIA_MATERIAL": [{"codigo": "HIERRO", "cantidad": 2}],
        },
        inspeccion_tecnica_req=True,
        tipos_inspeccion_tecnica=[{"codigo": "ELECTRICA"}],
        fecha_levantamiento=date(2026, 9, 8),
    )


async def test_finalizar_levantamiento_notifica_servicios_requeridos_traducidos() -> None:
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(
            estado="creado",
            id_levantamiento=_ID_LEVANTAMIENTO,
            numero_inspeccion=7,
            id_bien_inventario=_ID_BIEN_INVENTARIO,
        ),
        catalogo=_CATALOGO_BASE + _CATALOGO_SERVICIOS_REQUERIDOS,
    )
    ordenes_servicio_client = FakeOrdenesServicioClient()
    service = InspeccionService(repo=repo, ordenes_servicio_client=ordenes_servicio_client)  # type: ignore[arg-type]

    await service.finalizar_levantamiento(
        _INSPECCION_ID, _body_con_servicios_requeridos(), usuario="inspector@example.com"
    )

    assert len(ordenes_servicio_client.payloads) == 1
    payload = ordenes_servicio_client.payloads[0]
    assert payload["inspeccion_id"] == str(_INSPECCION_ID)
    assert payload["numero_inspeccion"] == "7"
    assert payload["id_bien_inventario"] == str(_ID_BIEN_INVENTARIO)
    assert payload["fecha_inspeccion"] == "2026-09-08T00:00:00Z"
    assert payload["latitud_inspeccion"] == pytest.approx(9.3405)
    assert payload["longitud_inspeccion"] == pytest.approx(-82.2500)
    assert payload["servicios_requeridos"] == [
        {
            "tipo_servicio": "LIMPIEZA",
            "subcategoria": "Retiro de Enseres",
            "cantidad": 1,
            "motivacion": None,
        },
        {
            "tipo_servicio": "CERRAJERIA",
            "subcategoria": "Hierro",
            "cantidad": 2,
            "motivacion": None,
        },
        {
            "tipo_servicio": "INSPECCIONES_ESPECIALES",
            "subcategoria": "Inspección Eléctrica",
            "cantidad": 1,
            "motivacion": None,
        },
    ]


async def test_finalizar_levantamiento_sin_servicios_requeridos_no_llama_webhook(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cuando servicios_requeridos e inspeccion_tecnica_req vienen vacíos, no hay nada que
    reportarle a ms-requerimientos: no debe llamarse el webhook, pero sí debe quedar un log
    explícito de que se omitió a propósito (para no confundir "no se llamó" con "se llamó
    y no se ve en los logs")."""
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(estado="creado", id_levantamiento=_ID_LEVANTAMIENTO)
    )
    ordenes_servicio_client = FakeOrdenesServicioClient()
    service = InspeccionService(repo=repo, ordenes_servicio_client=ordenes_servicio_client)  # type: ignore[arg-type]

    with caplog.at_level("INFO"):
        await service.finalizar_levantamiento(
            _INSPECCION_ID, _body(), usuario="inspector@example.com"
        )

    assert ordenes_servicio_client.payloads == []
    assert any(
        getattr(r, "event", None) == "ordenes_servicio_webhook_sin_servicios"
        for r in caplog.records
    )


async def test_finalizar_levantamiento_repetido_no_llama_webhook() -> None:
    respuesta_previa = {
        "id_levantamiento": str(_ID_LEVANTAMIENTO),
        "id_inspeccion": str(_INSPECCION_ID),
        "estado_inspeccion": "Finalizada",
        "mensaje": "Levantamiento finalizado correctamente",
    }
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(estado="repetido", respuesta_previa=respuesta_previa),
        catalogo=_CATALOGO_BASE + _CATALOGO_SERVICIOS_REQUERIDOS,
    )
    ordenes_servicio_client = FakeOrdenesServicioClient()
    service = InspeccionService(repo=repo, ordenes_servicio_client=ordenes_servicio_client)  # type: ignore[arg-type]

    await service.finalizar_levantamiento(
        _INSPECCION_ID, _body_con_servicios_requeridos(), usuario="inspector@example.com"
    )

    assert ordenes_servicio_client.payloads == []


async def test_finalizar_levantamiento_sin_coordenadas_omite_webhook() -> None:
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(
            estado="creado", id_levantamiento=_ID_LEVANTAMIENTO, numero_inspeccion=7
        ),
        catalogo=_CATALOGO_BASE + _CATALOGO_SERVICIOS_REQUERIDOS,
    )
    ordenes_servicio_client = FakeOrdenesServicioClient()
    service = InspeccionService(repo=repo, ordenes_servicio_client=ordenes_servicio_client)  # type: ignore[arg-type]
    body = _body_con_servicios_requeridos()
    body.coordenadas = None

    await service.finalizar_levantamiento(_INSPECCION_ID, body, usuario="inspector@example.com")

    assert ordenes_servicio_client.payloads == []


async def test_finalizar_levantamiento_webhook_fallido_no_rompe_la_respuesta() -> None:
    repo = LevantamientoServiceRepository(
        LevantamientoFinalizeResult(
            estado="creado", id_levantamiento=_ID_LEVANTAMIENTO, numero_inspeccion=7
        ),
        catalogo=_CATALOGO_BASE + _CATALOGO_SERVICIOS_REQUERIDOS,
    )
    ordenes_servicio_client = FakeOrdenesServicioClient(falla=True)
    service = InspeccionService(repo=repo, ordenes_servicio_client=ordenes_servicio_client)  # type: ignore[arg-type]

    respuesta, repetido = await service.finalizar_levantamiento(
        _INSPECCION_ID, _body_con_servicios_requeridos(), usuario="inspector@example.com"
    )

    assert repetido is False
    assert respuesta.id_levantamiento == _ID_LEVANTAMIENTO
    assert len(ordenes_servicio_client.payloads) == 1


def _con_coordenadas(valor: str | None) -> LevantamientoRequest:
    return LevantamientoRequest(
        id_operacion=uuid.uuid4(),
        coordenadas=valor,
        condicion_bien="BUENA",
        estado_ocupacion="DESOCUPADO",
        fecha_levantamiento=date(2026, 9, 8),
    )


@pytest.mark.parametrize("valor", [None, "9.3405,-82.2500", " 8.98 , -79.52 ", "-90,180"])
def test_coordenadas_validas(valor: str | None) -> None:
    assert _con_coordenadas(valor).coordenadas == valor


@pytest.mark.parametrize(
    "valor", ["abc", "9.3405", "1,2,3", "91,0", "0,181", "-90.1,0", "nan,0", ""]
)
def test_coordenadas_invalidas(valor: str) -> None:
    with pytest.raises(ValidationError):
        _con_coordenadas(valor)
