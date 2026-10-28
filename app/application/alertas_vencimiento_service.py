"""Job de alerta de inspección próxima a vencer (HU.5, líneas 226-227).

Reutiliza el mismo cálculo de "Estado de Alerta" que ya usa la pantalla de
Control de inspecciones (`InspeccionService.get_control` con
`alerta=AlertaGestion.PROXIMA` / `AlertaGestion.VENCIDA`), para que una finca
notificada acá sea exactamente la misma que el usuario ve marcada en esa
pantalla.

Pensado para correr una vez al día (8:00am, vía scheduler externo). Por
diseño, cada corrida crea una notificación nueva para cada finca próxima a
vencer, independientemente de si la de ayer ya fue leída o no: la idea es que
quede un historial/log de las alertas emitidas para esa finca (hasta 10, una
por cada día dentro de la ventana de "próxima a vencer"). Para que ese
historial no ensucie la bandeja activa del inspector, justo antes de crear la
de hoy se silencia (sin cerrar) la más reciente que haya quedado activa.
Cuando la inspección deja de estar "próxima" para pasar a "vencida" (fecha de
vencimiento ya en el pasado), la última notificación de "próxima a vencer"
que quedó activa se marca como vista y silenciada, porque esa alerta ya no
aplica.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application.gestion_catalogos import AlertaGestion
from app.application.inspeccion_service import InspeccionService
from app.application.notificacion_service import NotificacionService
from app.presentation.api.schemas.notificaciones import CrearNotificacionRequest

TIPO_NOTIFICACION_VENCIMIENTO = "INSPECCION_PROXIMA_A_VENCER"
_REFERENCIA_TIPO = "inspeccion"
_TITULO = "Inspección próxima a vencer"
_TAMANIO_PAGINA = 200


@dataclass
class AlertasVencimientoResultado:
    fincas_evaluadas: int
    notificaciones_creadas: int
    notificaciones_silenciadas: int
    fincas_omitidas_sin_inspector: int


class AlertasVencimientoService:
    def __init__(
        self,
        inspeccion_service: InspeccionService,
        notificacion_service: NotificacionService,
    ) -> None:
        self._inspecciones = inspeccion_service
        self._notificaciones = notificacion_service

    async def emitir(self, *, creado_por: str | None) -> AlertasVencimientoResultado:
        evaluadas = 0
        notificadas = 0
        silenciadas = 0
        omitidas = 0

        pagina = 1
        while True:
            response = await self._inspecciones.get_control(
                pagina=pagina,
                tamanio=_TAMANIO_PAGINA,
                numero_finca=None,
                estatus_bien_inventario=None,
                provincia=None,
                distrito=None,
                corregimiento=None,
                alerta=AlertaGestion.PROXIMA,
            )
            for item in response.data:
                evaluadas += 1
                if (
                    item.id_inspeccion is None
                    or item.inspeccion_email_inspector is None
                    or item.fecha_vencimiento is None
                ):
                    # Finca sin inspección activa (por lo tanto sin inspector
                    # asignado a quién notificar) aunque su última inspección
                    # finalizada esté próxima a vencer.
                    omitidas += 1
                    continue

                anterior = await self._notificaciones.get_ultima_activa_por_referencia(
                    email_destinatario=item.inspeccion_email_inspector,
                    referencia_tipo=_REFERENCIA_TIPO,
                    referencia_id=item.id_inspeccion,
                    tipo_notificacion=TIPO_NOTIFICACION_VENCIMIENTO,
                )
                if anterior is not None:
                    await self._notificaciones.marcar_silenciada_interno(
                        anterior, item.inspeccion_email_inspector
                    )
                    silenciadas += 1

                mensaje = (
                    f"La finca No. {item.numero_finca} se encuentra próxima a "
                    "inspeccionar, fecha de vencimiento "
                    f"{item.fecha_vencimiento:%d %m %Y}"
                )
                await self._notificaciones.crear_sin_cerrar_previas(
                    CrearNotificacionRequest(
                        email_destinatario=item.inspeccion_email_inspector,
                        tipo_notificacion=TIPO_NOTIFICACION_VENCIMIENTO,
                        titulo=_TITULO,
                        mensaje=mensaje,
                        referencia_tipo=_REFERENCIA_TIPO,
                        referencia_id=item.id_inspeccion,
                    ),
                    creado_por=creado_por,
                )
                notificadas += 1

            if pagina >= response.total_paginas:
                break
            pagina += 1

        silenciadas += await self._silenciar_alertas_de_fincas_vencidas()

        return AlertasVencimientoResultado(
            fincas_evaluadas=evaluadas,
            notificaciones_creadas=notificadas,
            notificaciones_silenciadas=silenciadas,
            fincas_omitidas_sin_inspector=omitidas,
        )

    async def _silenciar_alertas_de_fincas_vencidas(self) -> int:
        """Apaga la alerta de "próxima a vencer" de fincas que ya vencieron.

        Una finca que hoy está VENCIDA ya no aparece en el filtro PROXIMA de
        arriba, así que su última notificación (la del día en que dejó de estar
        próxima) nunca se tocaría de otro modo: se marca como vista y
        silenciada para que no siga reapareciendo por una alerta que ya no
        aplica.
        """
        silenciadas = 0
        pagina = 1
        while True:
            response = await self._inspecciones.get_control(
                pagina=pagina,
                tamanio=_TAMANIO_PAGINA,
                numero_finca=None,
                estatus_bien_inventario=None,
                provincia=None,
                distrito=None,
                corregimiento=None,
                alerta=AlertaGestion.VENCIDA,
            )
            for item in response.data:
                if item.id_inspeccion is None or item.inspeccion_email_inspector is None:
                    continue

                ultima = await self._notificaciones.get_ultima_activa_por_referencia(
                    email_destinatario=item.inspeccion_email_inspector,
                    referencia_tipo=_REFERENCIA_TIPO,
                    referencia_id=item.id_inspeccion,
                    tipo_notificacion=TIPO_NOTIFICACION_VENCIMIENTO,
                )
                if ultima is not None:
                    await self._notificaciones.marcar_vista_y_silenciada(
                        ultima, item.inspeccion_email_inspector
                    )
                    silenciadas += 1

            if pagina >= response.total_paginas:
                break
            pagina += 1

        return silenciadas
