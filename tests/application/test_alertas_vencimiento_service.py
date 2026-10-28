import uuid
from datetime import date
from typing import Any

from app.application.alertas_vencimiento_service import (
    TIPO_NOTIFICACION_VENCIMIENTO,
    AlertasVencimientoService,
)
from app.application.gestion_catalogos import AlertaGestion
from app.presentation.api.schemas.inspecciones import ControlItemResponse, ControlResponse
from app.presentation.api.schemas.notificaciones import CrearNotificacionRequest


def _control_item(**overrides: Any) -> ControlItemResponse:
    data: dict[str, Any] = {
        "id_bien_inventario": uuid.uuid4(),
        "id_bien": None,
        "no_registro": 1,
        "numero_finca": "F-001",
        "numeros_finca": ["F-001"],
        "nombre_deudor": None,
        "numero_prestamo": None,
        "id_tipo_propiedad": None,
        "tipo_propiedad": None,
        "id_provincia": None,
        "provincia": None,
        "id_distrito": None,
        "distrito": None,
        "id_corregimiento": None,
        "corregimiento": None,
        "barriada_sector": None,
        "direccion": None,
        "numero_lote": None,
        "latitud": None,
        "longitud": None,
        "url_ubicacion_geoespacial": None,
        "monto_adjudicado": None,
        "valor_avaluo": None,
        "estatus_bien": None,
        "color_badge": None,
        "estado_inventario": None,
        "oficinista": None,
        "usuario_registrador": None,
        "fecha_recibido_inventario": None,
        "fecha_creacion": None,
        "ruta_id": None,
        "ruta_nombre": None,
        "inspeccion_ruta_id": None,
        "inspeccion_ruta_nombre": None,
        "inspeccion_email_inspector": "inspector@example.com",
        "inspeccion_id_periodicidad": None,
        "inspeccion_periodicidad": None,
        "inspeccion_tipo_inspeccion": None,
        "inspeccion_descripcion_tipo": None,
        "tiene_inspeccion_activa": True,
        "id_inspeccion": uuid.uuid4(),
        "numero_inspeccion": "INSP-001",
        "estado_inspeccion": "PROXIMA",
        "color_alerta": "#ffc107",
        "color_badge_inspeccion": None,
        "fecha_programada": None,
        "fecha_realizada": None,
        "fecha_vencimiento": date(2026, 9, 15),
    }
    data.update(overrides)
    return ControlItemResponse(**data)


class FakeInspeccionService:
    """Simula get_control con páginas distintas según el filtro `alerta` recibido."""

    def __init__(
        self,
        proxima: list[list[ControlItemResponse]] | None = None,
        vencida: list[list[ControlItemResponse]] | None = None,
    ) -> None:
        self._paginas_por_alerta = {
            AlertaGestion.PROXIMA: proxima or [[]],
            AlertaGestion.VENCIDA: vencida or [[]],
        }
        self.calls: list[dict[str, Any]] = []

    async def get_control(self, **kwargs: Any) -> ControlResponse:
        self.calls.append(kwargs)
        pagina = kwargs["pagina"]
        paginas = self._paginas_por_alerta[kwargs["alerta"]]
        data = paginas[pagina - 1]
        return ControlResponse(
            data=data,
            pagina=pagina,
            tamanio=kwargs["tamanio"],
            total_registros=sum(len(p) for p in paginas),
            total_paginas=len(paginas),
        )


class FakeNotificacionService:
    def __init__(self, activas: dict[uuid.UUID, uuid.UUID] | None = None) -> None:
        self.creadas: list[tuple[CrearNotificacionRequest, str | None]] = []
        self.marcar_silenciada_interno_args: list[tuple[uuid.UUID, str]] = []
        self.marcar_vista_y_silenciada_args: list[tuple[uuid.UUID, str]] = []
        # Referencia_id (id_inspeccion) -> id_notificacion activa existente para ese email.
        self._activas = dict(activas or {})

    async def crear_sin_cerrar_previas(
        self, body: CrearNotificacionRequest, creado_por: str | None
    ) -> Any:
        self.creadas.append((body, creado_por))
        nueva_id = uuid.uuid4()
        self._activas[body.referencia_id] = nueva_id
        return type("Resp", (), {"id_notificacion": nueva_id})()

    async def get_ultima_activa_por_referencia(
        self,
        email_destinatario: str,
        referencia_tipo: str,
        referencia_id: uuid.UUID,
        tipo_notificacion: str,
    ) -> uuid.UUID | None:
        return self._activas.get(referencia_id)

    async def marcar_silenciada_interno(self, id_notificacion: uuid.UUID, email: str) -> None:
        self.marcar_silenciada_interno_args.append((id_notificacion, email))

    async def marcar_vista_y_silenciada(self, id_notificacion: uuid.UUID, email: str) -> None:
        self.marcar_vista_y_silenciada_args.append((id_notificacion, email))


async def test_emitir_crea_notificacion_cuando_no_existe_una_anterior() -> None:
    item = _control_item()
    inspecciones = FakeInspeccionService(proxima=[[item]])
    notificaciones = FakeNotificacionService()
    service = AlertasVencimientoService(inspecciones, notificaciones)  # type: ignore[arg-type]

    resultado = await service.emitir(creado_por="sistema@example.com")

    assert resultado.fincas_evaluadas == 1
    assert resultado.notificaciones_creadas == 1
    assert resultado.notificaciones_silenciadas == 0
    assert resultado.fincas_omitidas_sin_inspector == 0
    assert inspecciones.calls[0]["alerta"] == AlertaGestion.PROXIMA
    assert notificaciones.marcar_silenciada_interno_args == []

    body, creado_por = notificaciones.creadas[0]
    assert creado_por == "sistema@example.com"
    assert body.email_destinatario == "inspector@example.com"
    assert body.tipo_notificacion == TIPO_NOTIFICACION_VENCIMIENTO
    assert body.referencia_tipo == "inspeccion"
    assert body.referencia_id == item.id_inspeccion
    assert "F-001" in body.mensaje
    assert "15 09 2026" in body.mensaje


async def test_emitir_silencia_la_anterior_y_crea_una_nueva_independiente_de_si_fue_leida() -> None:
    item = _control_item()
    id_notificacion_anterior = uuid.uuid4()
    inspecciones = FakeInspeccionService(proxima=[[item]])
    notificaciones = FakeNotificacionService(
        activas={item.id_inspeccion: id_notificacion_anterior}
    )
    service = AlertasVencimientoService(inspecciones, notificaciones)  # type: ignore[arg-type]

    resultado = await service.emitir(creado_por=None)

    # Se crea una nueva SIEMPRE que ya exista una anterior, sin importar si se leyó.
    assert resultado.notificaciones_creadas == 1
    assert resultado.notificaciones_silenciadas == 1
    assert len(notificaciones.creadas) == 1
    assert notificaciones.marcar_silenciada_interno_args == [
        (id_notificacion_anterior, "inspector@example.com")
    ]


async def test_emitir_deja_un_log_de_una_notificacion_por_dia_para_la_misma_finca() -> None:
    item = _control_item()
    inspecciones = FakeInspeccionService(proxima=[[item]])
    notificaciones = FakeNotificacionService()
    service = AlertasVencimientoService(inspecciones, notificaciones)  # type: ignore[arg-type]

    # Simula 3 corridas diarias consecutivas para la misma finca.
    for _ in range(3):
        inspecciones.calls.clear()
        await service.emitir(creado_por=None)

    assert len(notificaciones.creadas) == 3
    # La 2da y 3ra corrida cada una silencia la de la corrida anterior.
    assert len(notificaciones.marcar_silenciada_interno_args) == 2


async def test_emitir_silencia_alerta_de_finca_que_paso_a_vencida() -> None:
    item = _control_item(estado_inspeccion="VENCIDA")
    id_notificacion = uuid.uuid4()
    inspecciones = FakeInspeccionService(proxima=[[]], vencida=[[item]])
    notificaciones = FakeNotificacionService(activas={item.id_inspeccion: id_notificacion})
    service = AlertasVencimientoService(inspecciones, notificaciones)  # type: ignore[arg-type]

    resultado = await service.emitir(creado_por=None)

    assert resultado.notificaciones_silenciadas == 1
    assert notificaciones.marcar_vista_y_silenciada_args == [
        (id_notificacion, "inspector@example.com")
    ]


async def test_emitir_no_silencia_finca_vencida_sin_notificacion_previa() -> None:
    item = _control_item(estado_inspeccion="VENCIDA")
    inspecciones = FakeInspeccionService(proxima=[[]], vencida=[[item]])
    notificaciones = FakeNotificacionService()
    service = AlertasVencimientoService(inspecciones, notificaciones)  # type: ignore[arg-type]

    resultado = await service.emitir(creado_por=None)

    assert resultado.notificaciones_silenciadas == 0
    assert notificaciones.marcar_vista_y_silenciada_args == []


async def test_emitir_omite_fincas_sin_inspector_asignado() -> None:
    item = _control_item(inspeccion_email_inspector=None, id_inspeccion=None)
    inspecciones = FakeInspeccionService(proxima=[[item]])
    notificaciones = FakeNotificacionService()
    service = AlertasVencimientoService(inspecciones, notificaciones)  # type: ignore[arg-type]

    resultado = await service.emitir(creado_por=None)

    assert resultado.fincas_evaluadas == 1
    assert resultado.notificaciones_creadas == 0
    assert resultado.fincas_omitidas_sin_inspector == 1
    assert notificaciones.creadas == []


async def test_emitir_recorre_todas_las_paginas_de_proximas() -> None:
    item_1 = _control_item(numero_finca="F-001")
    item_2 = _control_item(numero_finca="F-002")
    inspecciones = FakeInspeccionService(proxima=[[item_1], [item_2]])
    notificaciones = FakeNotificacionService()
    service = AlertasVencimientoService(inspecciones, notificaciones)  # type: ignore[arg-type]

    resultado = await service.emitir(creado_por=None)

    assert resultado.fincas_evaluadas == 2
    assert resultado.notificaciones_creadas == 2
    llamadas_proxima = [c for c in inspecciones.calls if c["alerta"] == AlertaGestion.PROXIMA]
    assert [c["pagina"] for c in llamadas_proxima] == [1, 2]


async def test_emitir_sin_resultados_no_crea_ni_silencia_nada() -> None:
    inspecciones = FakeInspeccionService()
    notificaciones = FakeNotificacionService()
    service = AlertasVencimientoService(inspecciones, notificaciones)  # type: ignore[arg-type]

    resultado = await service.emitir(creado_por=None)

    assert resultado.fincas_evaluadas == 0
    assert resultado.notificaciones_creadas == 0
    assert resultado.notificaciones_silenciadas == 0
    # Una página vacía por cada filtro (PROXIMA y VENCIDA).
    assert len(inspecciones.calls) == 2
