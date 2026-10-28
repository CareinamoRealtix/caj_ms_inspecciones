"""Lógica de negocio para inspecciones: orquesta repositorios y casos de uso."""
from __future__ import annotations

import hashlib
import itertools
import json
import logging
import math
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol

from app.application.gestion_catalogos import COLOR_ALERTA_GESTION, AlertaGestion
from app.application.levantamiento_validacion import (
    CodigoCatalogoInvalidoError,
    agrupar_opciones,
    validar_codigos,
)
from app.application.servicios_requeridos_translator import (
    ServicioSinTraduccionError,
    ServiciosRequeridosTranslator,
)
from app.infrastructure.clients.ordenes_servicio_client import (
    OrdenesServicioClient,
    OrdenesServicioWebhookError,
)
from app.infrastructure.database.inspeccion_repository import (
    ID_ESTATUS_BIEN_VENDIDO,
    InspeccionRepository,
    LevantamientoFinalizeResult,
)
from app.presentation.api.schemas.inspecciones import (
    CatalogoGestionItem,
    CatalogoResponse,
    ControlItemResponse,
    ControlResponse,
    CorregimientoGestionItem,
    DetalleInspeccionResponse,
    DistritoGestionItem,
    EstatusBienInventarioGestionItem,
    FormularioBatchCreateRequest,
    FormularioBatchCreateResponse,
    FormularioBatchItemResponse,
    FormularioCatalogosResponse,
    FormularioCreateRequest,
    FormularioCreateResponse,
    FormularioDetailResponse,
    FormularioUpdateRequest,
    FotografiaDetail,
    FotografiasInspeccionResponse,
    FotografiaUpdate,
    GestionCatalogosResponse,
    GestionItemResponse,
    GestionResponse,
    HistoricoItemResponse,
    HistoricoResponse,
    LevantamientoBatchItemResult,
    LevantamientoBatchRequest,
    LevantamientoBatchResponse,
    LevantamientoCatalogosResponse,
    LevantamientoDetail,
    LevantamientoOpcionOut,
    LevantamientoRequest,
    LevantamientoResponse,
    OcupanteDetail,
    PeriodicidadOut,
    RutaOut,
    SeleccionOpcion,
    SincronizacionCatalogoItem,
    SincronizacionCatalogosInventarioOut,
    SincronizacionCatalogosOut,
    SincronizacionCorregimientoItem,
    SincronizacionDistritoItem,
    SincronizacionFincaOut,
    SincronizacionInspeccionOut,
    SincronizacionMetaOut,
    SincronizacionResponse,
    SincronizacionUltimoLevantamientoOut,
    TipoInspeccionOut,
)
from app.presentation.api.schemas.inspectores import InspectorItem

logger = logging.getLogger(__name__)


class InspeccionAlreadyFinalizedError(Exception):
    """Operación no permitida sobre una inspección finalizada."""


class InspeccionNotFoundError(Exception):
    """La inspección solicitada no existe."""


class GestionLocationFiltersError(Exception):
    """Los filtros geográficos de gestión no respetan su jerarquía."""


class GestionDateFiltersError(Exception):
    """El rango de fechas de la última inspección no es válido."""


class PeriodicidadNotFoundError(Exception):
    """La periodicidad seleccionada no existe en el catálogo."""


class InspeccionActivaExistenteError(Exception):
    """Ya existe una inspección activa para este bien y número de finca."""

    def __init__(self, id_bien_inventario: uuid.UUID, numero_finca: str) -> None:
        self.id_bien_inventario = id_bien_inventario
        self.numero_finca = numero_finca
        super().__init__(
            f"Ya existe una inspección activa para el bien {id_bien_inventario} "
            f"y número de finca {numero_finca}"
        )


class LevantamientoOperacionConflictoError(Exception):
    """Un id_operacion no puede repetirse con otro contenido ni sobre una inspección finalizada."""

    def __init__(
        self,
        id_inspeccion: uuid.UUID,
        id_operacion: uuid.UUID,
        motivo: Literal["contenido_diferente", "ya_finalizada", "otra_inspeccion"],
    ) -> None:
        self.id_inspeccion = id_inspeccion
        self.id_operacion = id_operacion
        self.motivo = motivo
        if motivo == "contenido_diferente":
            mensaje = f"id_operacion {id_operacion} ya fue usado con un contenido distinto"
        elif motivo == "ya_finalizada":
            mensaje = f"La inspección {id_inspeccion} ya fue finalizada por otra operación"
        else:
            mensaje = (
                f"id_operacion {id_operacion} ya fue usado para finalizar otra inspección "
                f"distinta de {id_inspeccion}; genera un id_operacion nuevo por cada inspección"
            )
        super().__init__(mensaje)


def _parse_jsonb(value: Any) -> Any:
    """asyncpg devuelve columnas JSONB como texto crudo; lo decodificamos para tipar la salida."""
    if value is None:
        return None
    return json.loads(value)


def _format_numero_inspeccion(numero: int | None) -> str | None:
    if numero is None:
        return None
    return f"INSP-{numero:03d}"


def _classify_control_inspection_status(
    fecha_vencimiento: date | None,
    *,
    reference_date: date | None = None,
) -> str | None:
    if fecha_vencimiento is None:
        return None

    today = reference_date or date.today()
    if fecha_vencimiento < today:
        return AlertaGestion.VENCIDA.value
    if fecha_vencimiento <= today + timedelta(days=10):
        return AlertaGestion.PROXIMA.value
    return AlertaGestion.TERMINO.value


def _orden_vencimiento(
    fecha_vencimiento: date | None,
    *,
    reference_date: date | None = None,
) -> tuple[int, date]:
    """Clave de orden: VENCIDAS, PROXIMAS, A TÉRMINO y sin fecha (cada grupo por fecha ASC)."""
    estado = _classify_control_inspection_status(
        fecha_vencimiento, reference_date=reference_date
    )
    grupo = {
        AlertaGestion.VENCIDA.value: 0,
        AlertaGestion.PROXIMA.value: 1,
        AlertaGestion.TERMINO.value: 2,
    }.get(estado or "", 3)
    return grupo, fecha_vencimiento or date.max


def _color_for_estado_alerta(estado_inspeccion: str | None) -> str | None:
    if estado_inspeccion is None:
        return None
    return COLOR_ALERTA_GESTION.get(AlertaGestion(estado_inspeccion))


class FotosUrlSigner(Protocol):
    """Convierte la clave S3 guardada en la BD en una URL de CloudFront lista para el cliente."""

    def firmar_foto(self, referencia: str) -> str: ...


class InspeccionService:
    def __init__(
        self,
        repo: InspeccionRepository,
        ordenes_servicio_client: OrdenesServicioClient | None = None,
        fotos_signer: FotosUrlSigner | None = None,
    ) -> None:
        self._repo = repo
        self._fotos_signer = fotos_signer
        self._ordenes_servicio_client = ordenes_servicio_client
        self._servicios_translator = ServiciosRequeridosTranslator()

    def _url_foto(self, referencia: str | None) -> str | None:
        """URL de CloudFront (firmada si corresponde) de una clave S3 guardada en la BD."""
        if referencia is None or self._fotos_signer is None:
            return referencia
        return self._fotos_signer.firmar_foto(referencia)

    def _fotografias_detail(self, rows: list[Any]) -> list[FotografiaDetail]:
        fotos = [FotografiaDetail(**dict(f)) for f in rows]
        for foto in fotos:
            foto.url_s3 = self._url_foto(foto.url_s3) or foto.url_s3
        return fotos

    # ------------------------------------------------------------------
    # Catálogos
    # ------------------------------------------------------------------

    async def get_catalogo(self) -> CatalogoResponse:
        tipos, peris = await _gather(
            self._repo.get_tipos_inspeccion(),
            self._repo.get_periodicidades(),
        )
        return CatalogoResponse(
            tipos_inspeccion=[TipoInspeccionOut(**dict(r)) for r in tipos],
            periodicidades=[PeriodicidadOut(**dict(r)) for r in peris],
        )

    async def get_catalogos_formulario(
        self, inspectores: list[InspectorItem]
    ) -> FormularioCatalogosResponse:
        rutas, tipos, periodicidades = await _gather(
            self._repo.get_rutas(),
            self._repo.get_tipos_inspeccion(),
            self._repo.get_periodicidades(),
        )
        return FormularioCatalogosResponse(
            rutas=[RutaOut(**dict(row)) for row in rutas],
            inspectores=inspectores,
            tipos_inspeccion=[TipoInspeccionOut(**dict(row)) for row in tipos],
            periodicidades=[PeriodicidadOut(**dict(row)) for row in periodicidades],
        )

    async def get_catalogos_gestion(
        self, inspectores: list[InspectorItem]
    ) -> GestionCatalogosResponse:
        catalog_rows, route_rows = await _gather(
            self._repo.get_catalogos_gestion(),
            self._repo.get_rutas(),
        )
        rows = [dict(row) for row in catalog_rows]

        return GestionCatalogosResponse(
            inspectores=inspectores,
            estatus_bien_inventario=[
                EstatusBienInventarioGestionItem(id=row["id"], estado=row["nombre"])
                for row in rows
                if row["tipo_catalogo"] == "ESTADO_OCUPACION"
                and row["id"] != ID_ESTATUS_BIEN_VENDIDO
            ],
            alertas=[alerta.value for alerta in AlertaGestion],
            provincias=[
                CatalogoGestionItem(id=row["id"], nombre=row["nombre"])
                for row in rows
                if row["tipo_catalogo"] == "PROVINCIA"
            ],
            distritos=[
                DistritoGestionItem(
                    id=row["id"],
                    nombre=row["nombre"],
                    id_provincia=row["id_padre"],
                )
                for row in rows
                if row["tipo_catalogo"] == "DISTRITO"
            ],
            corregimientos=[
                CorregimientoGestionItem(
                    id=row["id"],
                    nombre=row["nombre"],
                    id_distrito=row["id_padre"],
                )
                for row in rows
                if row["tipo_catalogo"] == "CORREGIMIENTO"
            ],
            rutas=[RutaOut(**dict(row)) for row in route_rows],
        )

    # ------------------------------------------------------------------
    # Crear inspección
    # ------------------------------------------------------------------

    async def crear_inspeccion(
        self, body: FormularioCreateRequest, creado_por: str | None
    ) -> FormularioCreateResponse:
        id_inspeccion = uuid.uuid4()
        if await self._repo.get_periodicidad_dias(body.id_periodicidad) is None:
            raise PeriodicidadNotFoundError(body.id_periodicidad)

        activa = await self._repo.get_active_inspeccion_by_bien_finca(
            body.id_bien_inventario, body.numero_finca
        )
        if activa is not None:
            raise InspeccionActivaExistenteError(body.id_bien_inventario, body.numero_finca)

        numero = await self._repo.insert_inspeccion(
            id_inspeccion=id_inspeccion,
            id_bien_inventario=body.id_bien_inventario,
            numero_finca=body.numero_finca,
            ruta_id=body.ruta_id,
            ruta_nombre=body.ruta_nombre,
            id_tipo_inspeccion=body.id_tipo_inspeccion,
            id_periodicidad=body.id_periodicidad,
            email_inspector=body.email_inspector,
            fecha_programada=body.fecha_programada,
            fecha_vencimiento=None,
            descripcion_tipo=body.descripcion_tipo,
            creado_por=creado_por,
        )
        return FormularioCreateResponse(id_inspeccion=id_inspeccion, numero_inspeccion=numero)

    async def crear_inspecciones_batch(
        self, body: FormularioBatchCreateRequest, creado_por: str | None
    ) -> FormularioBatchCreateResponse:
        if await self._repo.get_periodicidad_dias(body.id_periodicidad) is None:
            raise PeriodicidadNotFoundError(body.id_periodicidad)

        ids_bienes = [bien.id_bien_inventario for bien in body.bienes]
        active_rows = await self._repo.get_active_batch_targets_for_bienes(ids_bienes)
        activas_por_bien_finca: dict[tuple[uuid.UUID, str], Any] = {}
        for row in active_rows:
            numero_finca = _normalize_numero_finca(row.get("numero_finca"))
            if numero_finca is None:
                continue
            activas_por_bien_finca[(row["id_bien_inventario"], numero_finca)] = row

        inspecciones_a_crear: list[dict[str, Any]] = []
        updates: list[dict[str, Any]] = []

        for bien in body.bienes:
            numero_finca = _normalize_numero_finca(bien.numero_finca)
            if numero_finca is None:
                continue
            key = (bien.id_bien_inventario, numero_finca)
            activa = activas_por_bien_finca.get(key)
            if activa is None:
                inspecciones_a_crear.append(
                    {
                        "id_inspeccion": uuid.uuid4(),
                        "id_bien_inventario": bien.id_bien_inventario,
                        "numero_finca": bien.numero_finca,
                        "ruta_id": body.ruta_id,
                        "ruta_nombre": body.ruta_nombre,
                        "id_tipo_inspeccion": body.id_tipo_inspeccion,
                        "id_periodicidad": body.id_periodicidad,
                        "email_inspector": body.email_inspector,
                        "fecha_programada": body.fecha_programada,
                        "descripcion_tipo": body.descripcion_tipo,
                        "fecha_vencimiento": None,
                    }
                )
                continue

            updates.append(
                {
                    "id_inspeccion": activa["id_inspeccion"],
                    "numero_inspeccion": activa["numero_inspeccion"],
                    "id_bien_inventario": bien.id_bien_inventario,
                    "numero_finca": bien.numero_finca,
                }
            )

        inserted = await self._repo.insert_inspecciones_batch(
            inspecciones=inspecciones_a_crear,
            creado_por=creado_por,
        )
        numeros_creados_por_id = {
            row["id_inspeccion"]: row["numero_inspeccion"] for row in inserted
        }

        numeros_actualizados_por_id: dict[uuid.UUID, int] = {}
        for item in updates:
            numero = await self._repo.update_inspeccion(
                id_inspeccion=item["id_inspeccion"],
                ruta_id=body.ruta_id,
                ruta_nombre=body.ruta_nombre,
                id_tipo_inspeccion=body.id_tipo_inspeccion,
                id_periodicidad=body.id_periodicidad,
                email_inspector=body.email_inspector,
                fecha_programada=body.fecha_programada,
                fecha_vencimiento=None,
                descripcion_tipo=body.descripcion_tipo,
                modificado_por=creado_por,
            )
            await self._repo.upsert_bien_inventario_ruta(
                id_bien_inventario=item["id_bien_inventario"],
                id_ruta=body.ruta_id,
                numero_finca=item["numero_finca"],
            )
            numeros_actualizados_por_id[item["id_inspeccion"]] = (
                numero if numero is not None else item["numero_inspeccion"]
            )

        items: list[FormularioBatchItemResponse] = []
        creadas_por_clave = {
            (item["id_bien_inventario"], _normalize_numero_finca(item["numero_finca"])): item
            for item in inspecciones_a_crear
            if _normalize_numero_finca(item["numero_finca"]) is not None
        }
        actualizadas_por_clave = {
            (item["id_bien_inventario"], _normalize_numero_finca(item["numero_finca"])): item
            for item in updates
            if _normalize_numero_finca(item["numero_finca"]) is not None
        }
        for bien in body.bienes:
            numero_finca = _normalize_numero_finca(bien.numero_finca)
            if numero_finca is None:
                continue
            key = (bien.id_bien_inventario, numero_finca)
            creada = creadas_por_clave.get(key)
            if creada is not None:
                items.append(
                    FormularioBatchItemResponse(
                        id_inspeccion=creada["id_inspeccion"],
                        numero_inspeccion=numeros_creados_por_id[creada["id_inspeccion"]],
                        id_bien_inventario=creada["id_bien_inventario"],
                        numero_finca=creada["numero_finca"],
                    )
                )
                continue
            actualizada = actualizadas_por_clave[key]
            items.append(
                FormularioBatchItemResponse(
                    id_inspeccion=actualizada["id_inspeccion"],
                    numero_inspeccion=numeros_actualizados_por_id[actualizada["id_inspeccion"]],
                    id_bien_inventario=actualizada["id_bien_inventario"],
                    numero_finca=actualizada["numero_finca"],
                )
            )

        return FormularioBatchCreateResponse(
            total_creadas=len(items),
            inspecciones=items,
        )

    # ------------------------------------------------------------------
    # Obtener formulario
    # ------------------------------------------------------------------

    async def get_formulario(self, id_inspeccion: uuid.UUID) -> FormularioDetailResponse:
        row = await self._repo.get_inspeccion_by_id(id_inspeccion)
        if row is None:
            raise InspeccionNotFoundError(id_inspeccion)
        return FormularioDetailResponse(
            id_inspeccion=row["id_inspeccion"],
            numero_inspeccion=row["numero_inspeccion"],
            id_bien_inventario=row["id_bien_inventario"],
            numero_finca=row["numero_finca"],
            ruta_id=row["ruta_id"],
            ruta_nombre=row["ruta_nombre"],
            id_tipo_inspeccion=row["id_tipo_inspeccion"],
            tipo_inspeccion=row["tipo_inspeccion"],
            descripcion_tipo=row["descripcion_tipo"],
            email_inspector=row["email_inspector"],
            estado_inspeccion=row["estado_inspeccion"],
            id_periodicidad=row["id_periodicidad"],
            periodicidad=row["periodicidad"],
            dias_vigencia=row["dias_vigencia"],
            fecha_programada=row["fecha_programada"],
            fecha_realizada=row["fecha_realizada"],
            fecha_vencimiento=row["fecha_vencimiento"],
            origen=row["origen"],
            activa=row["activa"],
            creado_por=row["creado_por"],
            fecha_creacion=row["fecha_creacion"],
        )

    # ------------------------------------------------------------------
    # Reprogramar inspección (PUT)
    # ------------------------------------------------------------------

    async def reprogramar_inspeccion(
        self,
        id_inspeccion: uuid.UUID,
        body: FormularioCreateRequest | FormularioUpdateRequest,
        modificado_por: str | None,
    ) -> FormularioCreateResponse:
        lifecycle = await self._repo.get_inspeccion_lifecycle(id_inspeccion)
        if lifecycle is None:
            raise InspeccionNotFoundError(id_inspeccion)
        if lifecycle["fecha_realizada"] is not None and not lifecycle["activa"]:
            raise InspeccionAlreadyFinalizedError(id_inspeccion)

        if await self._repo.get_periodicidad_dias(body.id_periodicidad) is None:
            raise PeriodicidadNotFoundError(body.id_periodicidad)

        numero = await self._repo.update_inspeccion(
            id_inspeccion=id_inspeccion,
            ruta_id=body.ruta_id,
            ruta_nombre=body.ruta_nombre,
            id_tipo_inspeccion=body.id_tipo_inspeccion,
            id_periodicidad=body.id_periodicidad,
            email_inspector=body.email_inspector,
            fecha_programada=body.fecha_programada,
            fecha_vencimiento=None,
            descripcion_tipo=body.descripcion_tipo,
            modificado_por=modificado_por,
        )
        # Si el body incluye `id_bien_inventario` y `numero_finca`, actualizar
        # la asignación de ruta en la tabla bien_inventario_ruta para mantener
        # la ruta predeterminada del bien sincronizada con la inspección.
        id_bien_inventario = getattr(body, "id_bien_inventario", None)
        numero_finca = getattr(body, "numero_finca", None)
        if id_bien_inventario is not None:
            await self._repo.upsert_bien_inventario_ruta(
                id_bien_inventario=id_bien_inventario,
                id_ruta=body.ruta_id,
                numero_finca=numero_finca,
            )
        return FormularioCreateResponse(
            id_inspeccion=id_inspeccion, numero_inspeccion=numero or 0
        )

    async def editar_inspeccion(
        self,
        id_inspeccion: uuid.UUID,
        body: FormularioUpdateRequest,
        modificado_por: str | None,
    ) -> FormularioCreateResponse:
        return await self.reprogramar_inspeccion(
            id_inspeccion=id_inspeccion,
            body=body,
            modificado_por=modificado_por,
        )

    # ------------------------------------------------------------------
    # Gestión de inventario (vista local + enrich de inspecciones)
    # ------------------------------------------------------------------

    async def get_gestion(
        self,
        pagina: int,
        tamanio: int,
        numero_finca: str | None,
        estatus_bien_inventario: int | None,
        provincia: int | None,
        distrito: int | None,
        corregimiento: int | None,
        nuevo_ingreso: bool = False,
        alerta: AlertaGestion | None = None,
        ruta: uuid.UUID | None = None,
        inspector: str | None = None,
        month_last_insp: int | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> GestionResponse:
        if corregimiento is not None and (provincia is None or distrito is None):
            raise GestionLocationFiltersError(
                "Para filtrar por corregimiento debe proporcionar provincia y distrito"
            )
        if distrito is not None and provincia is None:
            raise GestionLocationFiltersError(
                "Para filtrar por distrito debe proporcionar provincia"
            )
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise GestionDateFiltersError(
                "fecha_desde no puede ser posterior a fecha_hasta"
            )

        month_last_insp_value = (
            f"{date.today().year}-{month_last_insp:02d}"
            if month_last_insp is not None
            else None
        )

        return await self.get_inventario(
            pagina=pagina,
            tamanio=tamanio,
            numero_finca=numero_finca,
            id_estatus_bien=estatus_bien_inventario,
            id_provincia=provincia,
            id_distrito=distrito,
            id_corregimiento=corregimiento,
            nuevo_ingreso=nuevo_ingreso,
            alerta=alerta,
            ruta=ruta,
            inspector=inspector,
            month_last_insp=month_last_insp_value,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )

    async def get_control(
        self,
        pagina: int,
        tamanio: int,
        numero_finca: str | None,
        estatus_bien_inventario: int | None,
        provincia: int | None,
        distrito: int | None,
        corregimiento: int | None,
        alerta: AlertaGestion | None = None,
        inspector: str | None = None,
        month_expiration: int | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> ControlResponse:
        if corregimiento is not None and (provincia is None or distrito is None):
            raise GestionLocationFiltersError(
                "Para filtrar por corregimiento debe proporcionar provincia y distrito"
            )
        if distrito is not None and provincia is None:
            raise GestionLocationFiltersError(
                "Para filtrar por distrito debe proporcionar provincia"
            )
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise GestionDateFiltersError(
                "fecha_desde no puede ser posterior a fecha_hasta"
            )

        month_expiration_value = (
            f"{date.today().year}-{month_expiration:02d}"
            if month_expiration is not None
            else None
        )

        response = await self.get_inventario(
            pagina=pagina,
            tamanio=tamanio,
            numero_finca=numero_finca,
            id_estatus_bien=estatus_bien_inventario,
            id_provincia=provincia,
            id_distrito=distrito,
            id_corregimiento=corregimiento,
            nuevo_ingreso=False,
            requiere_inspeccion_finalizada=True,
            alerta=alerta,
            ruta=None,
            inspector=inspector,
            month_expiration=month_expiration_value,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        control_items = []
        for item in response.data:
            item_data = item.model_dump(exclude={"estado_inspeccion"})
            control_items.append(
                ControlItemResponse(**item_data, estado_inspeccion=item.estado_alerta)
            )
        return ControlResponse(
            data=control_items,
            pagina=response.pagina,
            tamanio=response.tamanio,
            total_registros=response.total_registros,
            total_paginas=response.total_paginas,
        )

    async def get_inventario(
        self,
        *,
        pagina: int,
        tamanio: int,
        numero_finca: str | None = None,
        id_estatus_bien: int | None = None,
        id_provincia: int | None = None,
        id_distrito: int | None = None,
        id_corregimiento: int | None = None,
        nuevo_ingreso: bool = False,
        requiere_inspeccion_finalizada: bool = False,
        alerta: AlertaGestion | None = None,
        ruta: uuid.UUID | None = None,
        inspector: str | None = None,
        month_last_insp: str | None = None,
        month_expiration: str | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> GestionResponse:
        numero_finca_filter = _normalize_numero_finca(numero_finca)
        rows, total = await self._repo.get_inventario(
            pagina=pagina,
            tamanio=tamanio,
            numero_finca=numero_finca_filter,
            id_estatus_bien=id_estatus_bien,
            id_provincia=id_provincia,
            id_distrito=id_distrito,
            id_corregimiento=id_corregimiento,
            nuevo_ingreso=nuevo_ingreso,
            requiere_inspeccion_finalizada=requiere_inspeccion_finalizada,
            alerta=alerta,
            ruta=ruta,
            inspector=inspector,
            month_last_insp=month_last_insp,
            month_expiration=month_expiration,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )

        bienes = [dict(row) for row in rows]
        ids = list(dict.fromkeys(_to_uuid(b["id_bien_inventario"]) for b in bienes))

        inspeccion_map: dict[tuple[uuid.UUID, str], Any] = {}
        ultima_inspeccion_map: dict[tuple[uuid.UUID, str], Any] = {}
        ruta_map: dict[tuple[uuid.UUID, str], Any] = {}
        if ids:
            rows = await self._repo.get_active_inspections_for_bienes(ids)
            for row in rows:
                bid = _to_uuid(row["id_bien_inventario"])
                row_numero_finca = _normalize_numero_finca(row.get("numero_finca"))
                if row_numero_finca is None:
                    continue
                inspeccion_map[(bid, row_numero_finca)] = row
            rows = await self._repo.get_latest_completed_inspections_for_bienes(ids)
            for row in rows:
                bid = _to_uuid(row["id_bien_inventario"])
                row_numero_finca = _normalize_numero_finca(row.get("numero_finca"))
                if row_numero_finca is None:
                    continue
                ultima_inspeccion_map[(bid, row_numero_finca)] = row
            rows = await self._repo.get_bien_inventario_rutas_for_bienes(ids)
            for row in rows:
                bid = _to_uuid(row["id_bien_inventario"])
                row_numero_finca = _normalize_numero_finca(row.get("numero_finca"))
                if row_numero_finca is None:
                    continue
                ruta_map[(bid, row_numero_finca)] = row

        items = []
        today = date.today()
        for b in bienes:
            bid = _to_uuid(b["id_bien_inventario"])
            numeros_finca = _normalize_numeros_finca(
                b.get("numeros_finca"),
                b.get("numero_finca"),
            )
            # El repositorio pagina por (bien, finca): cada fila trae su propia finca.
            item_numero_finca = b.get("numero_finca_item")
            lookup = _normalize_numero_finca(item_numero_finca)
            # Omitir bienes que no tengan `numero_finca` normalizado
            if lookup is None:
                continue
            insp = inspeccion_map.get((bid, lookup))
            ultima_insp = ultima_inspeccion_map.get((bid, lookup))
            ruta_asignada = ruta_map.get((bid, lookup))
            fecha_vencimiento = (
                insp["fecha_vencimiento"]
                if insp and insp["fecha_vencimiento"] is not None
                else ultima_insp["fecha_vencimiento"]
                if ultima_insp and ultima_insp["fecha_vencimiento"] is not None
                else b["fecha_vencimiento_orden"]
                if b.get("fecha_vencimiento_orden") is not None
                else None
            )
            estado_alerta = _classify_control_inspection_status(
                fecha_vencimiento, reference_date=today
            )
            items.append(
                GestionItemResponse(
                    id_bien_inventario=bid,
                    id_bien=b.get("id_bien"),
                    no_registro=b["no_registro"],
                    numero_finca=item_numero_finca,
                    numeros_finca=numeros_finca,
                    nombre_deudor=b.get("nombre_deudor"),
                    numero_prestamo=b.get("numero_prestamo"),
                    id_tipo_propiedad=b.get("id_tipo_propiedad"),
                    tipo_propiedad=b.get("tipo_propiedad"),
                    id_provincia=b.get("id_provincia"),
                    provincia=b.get("provincia"),
                    id_distrito=b.get("id_distrito"),
                    distrito=b.get("distrito"),
                    id_corregimiento=b.get("id_corregimiento"),
                    corregimiento=b.get("corregimiento"),
                    barriada_sector=b.get("barriada_sector"),
                    direccion=b.get("direccion"),
                    numero_lote=b.get("numero_lote"),
                    latitud=b.get("latitud"),
                    longitud=b.get("longitud"),
                    url_ubicacion_geoespacial=b.get("url_ubicacion_geoespacial"),
                    monto_adjudicado=b.get("monto_adjudicado"),
                    valor_avaluo=b.get("valor_avaluo"),
                    estatus_bien=b.get("estatus_bien"),
                    color_badge=b.get("color_badge"),
                    estado_inventario=b.get("estado_inventario"),
                    oficinista=b.get("oficinista"),
                    usuario_registrador=b.get("usuario_registrador"),
                    fecha_recibido_inventario=b.get("fecha_recibido_inventario"),
                    fecha_creacion=b.get("fecha_creacion"),
                    ruta_id=(
                        insp["ruta_id"]
                        if insp and insp.get("ruta_id") is not None
                        else ruta_asignada["id_ruta"] if ruta_asignada else None
                    ),
                    ruta_nombre=(
                        insp["ruta_nombre"]
                        if insp and insp.get("ruta_nombre") is not None
                        else ruta_asignada["ruta_nombre"] if ruta_asignada else None
                    ),
                    inspeccion_ruta_id=insp.get("ruta_id") if insp else None,
                    inspeccion_ruta_nombre=(
                        insp.get("ruta_nombre") if insp else None
                    ),
                    inspeccion_email_inspector=(
                        insp.get("email_inspector") if insp else None
                    ),
                    inspeccion_id_periodicidad=(
                        insp.get("id_periodicidad") if insp else None
                    ),
                    inspeccion_periodicidad=(
                        insp.get("periodicidad") if insp else None
                    ),
                    inspeccion_tipo_inspeccion=(
                        insp.get("tipo_inspeccion") if insp else None
                    ),
                    inspeccion_descripcion_tipo=(
                        insp.get("descripcion_tipo") if insp else None
                    ),
                    tiene_inspeccion_activa=insp is not None,
                    id_inspeccion=insp["id_inspeccion"] if insp else None,
                    numero_inspeccion=(
                        _format_numero_inspeccion(
                            ultima_insp["numero_inspeccion"]
                        )
                        if requiere_inspeccion_finalizada and ultima_insp
                        else None
                    ),
                    estado_inspeccion=insp["estado_inspeccion"] if insp else None,
                    color_badge_inspeccion=insp["color_badge"] if insp else None,
                    fecha_programada=insp["fecha_programada"] if insp else None,
                    fecha_realizada=(
                        ultima_insp["fecha_realizada"] if ultima_insp else None
                    ),
                    fecha_vencimiento=fecha_vencimiento,
                    estado_alerta=estado_alerta,
                    color_alerta=_color_for_estado_alerta(estado_alerta),
                )
            )

        # Las fincas de un mismo bien (filas contiguas) van VENCIDAS, PROXIMAS, A TÉRMINO y
        # sin fecha; el orden entre bienes ya lo resolvió la consulta antes de paginar.
        items = [
            item
            for _, grupo in itertools.groupby(items, key=lambda item: item.id_bien_inventario)
            for item in sorted(
                grupo,
                key=lambda item: _orden_vencimiento(
                    item.fecha_vencimiento, reference_date=today
                ),
            )
        ]

        return GestionResponse(
            data=items,
            pagina=pagina,
            tamanio=tamanio,
            total_registros=total,
            total_paginas=math.ceil(total / tamanio) if total else 0,
        )

    # ------------------------------------------------------------------
    # Histórico
    # ------------------------------------------------------------------

    async def get_historico(
        self,
        numero_finca: str | None,
        pagina: int,
        tamanio: int,
        provincia: int | None = None,
        distrito: int | None = None,
        corregimiento: int | None = None,
        ruta: uuid.UUID | None = None,
        inspector: str | None = None,
        month_last_insp: int | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> HistoricoResponse:
        if corregimiento is not None and (provincia is None or distrito is None):
            raise GestionLocationFiltersError(
                "Para filtrar por corregimiento debe proporcionar provincia y distrito"
            )
        if distrito is not None and provincia is None:
            raise GestionLocationFiltersError(
                "Para filtrar por distrito debe proporcionar provincia"
            )
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise GestionDateFiltersError(
                "fecha_desde no puede ser posterior a fecha_hasta"
            )

        month_last_insp_value = (
            f"{date.today().year}-{month_last_insp:02d}"
            if month_last_insp is not None
            else None
        )

        rows, total = await self._repo.get_historico_by_finca(
            _normalize_numero_finca(numero_finca),
            pagina,
            tamanio,
            id_provincia=provincia,
            id_distrito=distrito,
            id_corregimiento=corregimiento,
            ruta=ruta,
            inspector=inspector,
            month_last_insp=month_last_insp_value,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        items = [
            HistoricoItemResponse(
                id_inspeccion=r["id_inspeccion"],
                id_bien_inventario=r["id_bien_inventario"],
                numero_finca=r["numero_finca"],
                numero_inspeccion=_format_numero_inspeccion(r["numero_inspeccion"]),
                email_inspector=r["email_inspector"],
                fecha_programada=r["fecha_programada"],
                fecha_realizada=r["fecha_realizada"],
                fecha_vencimiento=r["fecha_vencimiento"],
                fecha_creacion=r["fecha_creacion"],
                fecha_modificacion=r["fecha_modificacion"],
                activa=r["activa"],
                estado_inspeccion=r["estado_inspeccion"],
            )
            for r in rows
        ]
        return HistoricoResponse(
            data=items,
            pagina=pagina,
            tamanio=tamanio,
            total_registros=total,
            total_paginas=math.ceil(total / tamanio) if total else 0,
        )

    # ------------------------------------------------------------------
    # Detalle completo
    # ------------------------------------------------------------------

    async def get_detalle(self, id_inspeccion: uuid.UUID) -> DetalleInspeccionResponse:
        row = await self._repo.get_detalle(id_inspeccion)
        if row is None:
            raise InspeccionNotFoundError(id_inspeccion)

        fotos_rows = await self._repo.get_fotografias_by_inspeccion(id_inspeccion)

        levantamiento = None
        if row["id_levantamiento"] is not None:
            levantamiento = LevantamientoDetail(
                coordenadas=row["coordenadas"],
                condicion_bien=row["condicion_bien"],
                estado_ocupacion=row["estado_ocupacion"],
                ocupante=OcupanteDetail(
                    nombre=row["nombre_ocupante"],
                    tipo_identificacion=row["tipo_identificacion_ocup"],
                    numero_identificacion=row["numero_identificacion_ocup"],
                    numero_contacto=row["numero_contacto_ocupante"],
                    comentarios=row["comentarios_ocupante"],
                ),
                puertas=_parse_jsonb(row["puertas"]),
                tipos_ventanas=_parse_jsonb(row["tipos_ventanas"]),
                servicios_publicos=_parse_jsonb(row["servicios_publicos"]),
                distribucion_inmueble=_parse_jsonb(row["distribucion_inmueble"]),
                servicios_requeridos=_parse_jsonb(row["servicios_requeridos"]),
                inspeccion_tecnica_req=row["inspeccion_tecnica_req"],
                tipos_inspeccion_tecnica=_parse_jsonb(row["tipos_inspeccion_tecnica"]),
                motivacion=row["motivacion"],
                url_firma_inspector=self._url_foto(row["url_firma_inspector"]),
                observaciones=row["observaciones"],
                fecha_levantamiento=row["fecha_levantamiento"],
            )

        return DetalleInspeccionResponse(
            id_inspeccion=row["id_inspeccion"],
            numero_inspeccion=row["numero_inspeccion"],
            numero_finca=row["numero_finca"],
            id_bien_inventario=row["id_bien_inventario"],
            ruta_id=row["ruta_id"],
            ruta_nombre=row["ruta_nombre"],
            fecha_programada=row["fecha_programada"],
            fecha_realizada=row["fecha_realizada"],
            tipo_inspeccion=row["tipo_inspeccion"],
            descripcion_tipo=row["descripcion_tipo"],
            email_inspector=row["email_inspector"],
            estado_inspeccion=row["estado_inspeccion"],
            color_badge=row["color_badge"],
            origen=row["origen"],
            provincia=row["provincia"],
            distrito=row["distrito"],
            corregimiento=row["corregimiento"],
            barriada_sector=row["barriada_sector"],
            direccion=row["direccion"],
            numero_lote=row["numero_lote"],
            levantamiento=levantamiento,
            fotografias=self._fotografias_detail(fotos_rows),
        )

    # ------------------------------------------------------------------
    # Fotografías
    # ------------------------------------------------------------------

    async def get_fotografias(self, id_inspeccion: uuid.UUID) -> FotografiasInspeccionResponse:
        if await self._repo.get_inspeccion_lifecycle(id_inspeccion) is None:
            raise InspeccionNotFoundError(id_inspeccion)

        fotos_rows = await self._repo.get_fotografias_by_inspeccion(id_inspeccion)
        return FotografiasInspeccionResponse(
            id_inspeccion=id_inspeccion,
            fotografias=self._fotografias_detail(fotos_rows),
        )

    async def update_fotografias(
        self,
        id_inspeccion: uuid.UUID,
        fotografias: list[FotografiaUpdate],
    ) -> None:
        await self._repo.update_fotografias(
            id_inspeccion,
            [f.model_dump() for f in fotografias],
        )

    # ------------------------------------------------------------------
    # Levantamiento
    # ------------------------------------------------------------------

    async def get_catalogos_levantamiento(self) -> LevantamientoCatalogosResponse:
        rows = await self._repo.get_levantamiento_opciones_activas()
        catalogos: dict[str, list[LevantamientoOpcionOut]] = {}
        for row in rows:
            catalogos.setdefault(row["tipo_catalogo"], []).append(
                LevantamientoOpcionOut(
                    codigo=row["codigo"],
                    nombre=row["nombre"],
                    requiere_cantidad=row["requiere_cantidad"],
                    permite_descripcion=row["permite_descripcion"],
                    orden=row["orden"],
                )
            )
        return LevantamientoCatalogosResponse(
            version=datetime.now(UTC),
            catalogos=catalogos,
        )

    # ------------------------------------------------------------------
    # Sincronización offline (HU.12) — endpoint provisional
    # ------------------------------------------------------------------

    async def get_sincronizacion(self, email_inspector: str) -> SincronizacionResponse:
        (
            tipos,
            periodicidades,
            rutas,
            opciones_rows,
            catalogos_inventario_rows,
            inspecciones_rows,
        ) = await _gather(
            self._repo.get_tipos_inspeccion(),
            self._repo.get_periodicidades(),
            self._repo.get_rutas(),
            self._repo.get_levantamiento_opciones_activas(),
            self._repo.get_catalogos_gestion(),
            self._repo.get_sincronizacion_inspecciones(email_inspector),
        )

        levantamiento_opciones: dict[str, list[LevantamientoOpcionOut]] = {}
        for row in opciones_rows:
            levantamiento_opciones.setdefault(row["tipo_catalogo"], []).append(
                LevantamientoOpcionOut(
                    codigo=row["codigo"],
                    nombre=row["nombre"],
                    requiere_cantidad=row["requiere_cantidad"],
                    permite_descripcion=row["permite_descripcion"],
                    orden=row["orden"],
                )
            )

        catalogo_gestion_rows = [dict(row) for row in catalogos_inventario_rows]
        catalogos_inventario = SincronizacionCatalogosInventarioOut(
            estatus_bien_inventario=[
                SincronizacionCatalogoItem(id=row["id"], nombre=row["nombre"])
                for row in catalogo_gestion_rows
                if row["tipo_catalogo"] == "ESTADO_OCUPACION"
            ],
            provincias=[
                SincronizacionCatalogoItem(id=row["id"], nombre=row["nombre"])
                for row in catalogo_gestion_rows
                if row["tipo_catalogo"] == "PROVINCIA"
            ],
            distritos=[
                SincronizacionDistritoItem(
                    id=row["id"], nombre=row["nombre"], id_provincia=row["id_padre"]
                )
                for row in catalogo_gestion_rows
                if row["tipo_catalogo"] == "DISTRITO"
            ],
            corregimientos=[
                SincronizacionCorregimientoItem(
                    id=row["id"], nombre=row["nombre"], id_distrito=row["id_padre"]
                )
                for row in catalogo_gestion_rows
                if row["tipo_catalogo"] == "CORREGIMIENTO"
            ],
        )

        catalogos = SincronizacionCatalogosOut(
            version=datetime.now(UTC),
            tipos_inspeccion=[TipoInspeccionOut(**dict(r)) for r in tipos],
            periodicidades=[PeriodicidadOut(**dict(r)) for r in periodicidades],
            rutas=[RutaOut(**dict(r)) for r in rutas],
            levantamiento_opciones=levantamiento_opciones,
            catalogos_inventario=catalogos_inventario,
        )

        inspecciones: list[SincronizacionInspeccionOut] = []
        for row in inspecciones_rows:
            ultimo_levantamiento = None
            if row["ul_fecha_levantamiento"] is not None:
                ultimo_levantamiento = SincronizacionUltimoLevantamientoOut(
                    id_inspeccion=row["ul_id_inspeccion"],
                    numero_inspeccion=row["ul_numero_inspeccion"],
                    fecha_levantamiento=row["ul_fecha_levantamiento"],
                    coordenadas=row["ul_coordenadas"],
                    condicion_bien=row["ul_condicion_bien"],
                    estado_ocupacion=row["ul_estado_ocupacion"],
                    nombre_ocupante=row["ul_nombre_ocupante"],
                    ocupante=OcupanteDetail(
                        nombre=row["ul_nombre_ocupante"],
                        tipo_identificacion=row["ul_tipo_identificacion_ocup"],
                        numero_identificacion=row["ul_numero_identificacion_ocup"],
                        numero_contacto=row["ul_numero_contacto_ocupante"],
                        comentarios=row["ul_comentarios_ocupante"],
                    ),
                    puertas=_parse_jsonb(row["ul_puertas"]),
                    tipos_ventanas=_parse_jsonb(row["ul_tipos_ventanas"]),
                    distribucion_inmueble=_parse_jsonb(row["ul_distribucion_inmueble"]),
                    servicios_publicos=_parse_jsonb(row["ul_servicios_publicos"]),
                    observaciones=row["ul_observaciones"],
                )

            finca = SincronizacionFincaOut(
                id_bien_inventario=row["id_bien_inventario"],
                id_bien=row["id_bien"],
                numero_finca=row["numero_finca"],
                numeros_finca=list(row["numeros_finca"] or []),
                nombre_deudor=row["nombre_deudor"],
                numero_prestamo=row["numero_prestamo"],
                tipo_propiedad=row["tipo_propiedad"],
                direccion=row["direccion"],
                provincia=row["provincia"],
                distrito=row["distrito"],
                corregimiento=row["corregimiento"],
                barriada_sector=row["barriada_sector"],
                numero_lote=row["numero_lote"],
                latitud=row["latitud"],
                longitud=row["longitud"],
                url_ubicacion_geoespacial=row["url_ubicacion_geoespacial"],
                id_estatus_bien=row["id_estatus_bien"],
                estatus_bien=row["estatus_bien"],
                color_badge=row["color_badge"],
                id_estado_inventario=row["id_estado_inventario"],
                estado_inventario=row["estado_inventario"],
            )

            inspecciones.append(
                SincronizacionInspeccionOut(
                    id_inspeccion=row["id_inspeccion"],
                    numero_inspeccion=row["numero_inspeccion"],
                    fecha_programada=row["fecha_programada"],
                    fecha_vencimiento=row["fecha_vencimiento"],
                    origen=row["origen"],
                    id_tipo_inspeccion=row["id_tipo_inspeccion"],
                    descripcion_tipo=row["descripcion_tipo"],
                    id_periodicidad=row["id_periodicidad"],
                    ruta_id=row["ruta_id"],
                    ruta_nombre=row["ruta_nombre"],
                    finca=finca,
                    ultimo_levantamiento=ultimo_levantamiento,
                )
            )

        return SincronizacionResponse(
            meta=SincronizacionMetaOut(
                email_inspector=email_inspector,
                fecha_referencia=date.today(),
                fecha_generacion=datetime.now(UTC),
                total_inspecciones=len(inspecciones),
            ),
            catalogos=catalogos,
            rutas_optimas=[],
            inspecciones=inspecciones,
        )

    async def finalizar_levantamiento(
        self,
        id_inspeccion: uuid.UUID,
        body: LevantamientoRequest,
        usuario: str | None,
    ) -> tuple[LevantamientoResponse, bool]:
        """Finaliza un levantamiento. Retorna (respuesta, es_repetido)."""
        opciones = agrupar_opciones(await self._repo.get_levantamiento_opciones_activas())
        validar_codigos(body, opciones)

        contenido = body.model_dump(mode="json", exclude={"id_operacion"})
        contenido_hash = hashlib.sha256(
            json.dumps(contenido, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        resultado = await self._repo.finalizar_levantamiento(
            id_inspeccion=id_inspeccion,
            id_operacion=body.id_operacion,
            contenido_hash=contenido_hash,
            data=body.model_dump(exclude={"id_operacion", "fotografias"}),
            fotografias=[f.model_dump() for f in body.fotografias],
            fecha_levantamiento=body.fecha_levantamiento,
            creado_por=usuario,
        )

        if resultado.estado == "no_encontrada":
            raise InspeccionNotFoundError(id_inspeccion)
        if resultado.estado == "conflicto_contenido":
            raise LevantamientoOperacionConflictoError(
                id_inspeccion, body.id_operacion, "contenido_diferente"
            )
        if resultado.estado == "ya_finalizada":
            raise LevantamientoOperacionConflictoError(
                id_inspeccion, body.id_operacion, "ya_finalizada"
            )
        if resultado.estado == "operacion_de_otra_inspeccion":
            raise LevantamientoOperacionConflictoError(
                id_inspeccion, body.id_operacion, "otra_inspeccion"
            )
        if resultado.estado == "repetido":
            return LevantamientoResponse(**(resultado.respuesta_previa or {})), True

        await self._notificar_servicios_requeridos(id_inspeccion, body, resultado)

        return (
            LevantamientoResponse(
                id_levantamiento=resultado.id_levantamiento,
                id_inspeccion=id_inspeccion,
                estado_inspeccion="Finalizada",
                mensaje="Levantamiento finalizado correctamente",
            ),
            False,
        )

    async def finalizar_levantamiento_batch(
        self,
        body: LevantamientoBatchRequest,
        usuario: str | None,
    ) -> LevantamientoBatchResponse:
        """Finaliza el levantamiento de varias inspecciones en un solo llamado.

        Cada ítem se procesa con exactamente la misma lógica y las mismas consecuencias
        (validación de catálogos, idempotencia por id_operacion, persistencia de
        fotografías y webhook a ms-requerimientos) que `finalizar_levantamiento`, uno a la
        vez. Un ítem inválido o en conflicto no aborta el lote: se reporta como fallido y
        se continúa con los siguientes.
        """
        resultados: list[LevantamientoBatchItemResult] = []

        for item in body.levantamientos:
            levantamiento = LevantamientoRequest(**item.model_dump(exclude={"id_inspeccion"}))
            try:
                resultado, repetido = await self.finalizar_levantamiento(
                    item.id_inspeccion, levantamiento, usuario=usuario
                )
            except InspeccionNotFoundError:
                resultados.append(
                    LevantamientoBatchItemResult(
                        id_inspeccion=item.id_inspeccion,
                        exito=False,
                        codigo_error="no_encontrada",
                    )
                )
                continue
            except LevantamientoOperacionConflictoError as exc:
                resultados.append(
                    LevantamientoBatchItemResult(
                        id_inspeccion=item.id_inspeccion,
                        exito=False,
                        codigo_error=exc.motivo,
                    )
                )
                continue
            except CodigoCatalogoInvalidoError:
                resultados.append(
                    LevantamientoBatchItemResult(
                        id_inspeccion=item.id_inspeccion,
                        exito=False,
                        codigo_error="codigo_catalogo_invalido",
                    )
                )
                continue

            resultados.append(
                LevantamientoBatchItemResult(
                    id_inspeccion=item.id_inspeccion,
                    exito=True,
                    repetido=repetido,
                    id_levantamiento=resultado.id_levantamiento,
                    estado_inspeccion=resultado.estado_inspeccion,
                    mensaje=resultado.mensaje,
                )
            )

        exitosos = sum(1 for r in resultados if r.exito)
        return LevantamientoBatchResponse(
            total=len(resultados),
            exitosos=exitosos,
            fallidos=len(resultados) - exitosos,
            resultados=resultados,
        )

    async def _notificar_servicios_requeridos(
        self,
        id_inspeccion: uuid.UUID,
        body: LevantamientoRequest,
        resultado: LevantamientoFinalizeResult,
    ) -> None:
        """Reporta a ms-requerimientos (órdenes de servicio) los servicios_requeridos y/o la
        inspección técnica marcados en el levantamiento. Best-effort: un fallo del webhook (o
        del cliente deshabilitado) se loguea pero nunca revierte ni falla la finalización, que
        ya quedó confirmada en la base de datos."""
        if self._ordenes_servicio_client is None:
            return

        try:
            payload = _construir_payload_servicios_requeridos(
                id_inspeccion=id_inspeccion,
                resultado=resultado,
                body=body,
                translator=self._servicios_translator,
            )
        except ServicioSinTraduccionError:
            logger.exception(
                "No se pudo traducir un servicio requerido para ms-requerimientos",
                extra={
                    "event": "ordenes_servicio_traduccion_fallida",
                    "id_inspeccion": str(id_inspeccion),
                },
            )
            return

        if payload is None:
            return

        try:
            await self._ordenes_servicio_client.notificar_servicios_requeridos(payload)
        except OrdenesServicioWebhookError:
            logger.warning(
                "No se pudo notificar servicios_requeridos a ms-requerimientos",
                extra={
                    "event": "ordenes_servicio_webhook_fallo",
                    "id_inspeccion": str(id_inspeccion),
                },
            )


# ------------------------------------------------------------------
# Payload del webhook de servicios_requeridos (ms-requerimientos)
# ------------------------------------------------------------------

def _parsear_coordenadas(coordenadas: str | None) -> tuple[float, float] | None:
    if not coordenadas:
        return None
    partes = coordenadas.split(",")
    if len(partes) != 2:
        return None
    try:
        return float(partes[0].strip()), float(partes[1].strip())
    except ValueError:
        return None


def _traducir_seleccion(
    tipo_interno: str,
    seleccion: SeleccionOpcion,
    translator: ServiciosRequeridosTranslator,
) -> dict[str, Any]:
    tipo_externo, subcategoria = translator.traducir(tipo_interno, seleccion.codigo)
    return {
        "tipo_servicio": tipo_externo,
        "subcategoria": subcategoria,
        # ms-requerimientos exige un entero (probado con su webhook: 422 "int_type" ante
        # null). La mayoría de nuestros catálogos no piden cantidad al inspector, así que
        # ausente = una unidad del servicio.
        "cantidad": seleccion.cantidad if seleccion.cantidad is not None else 1,
        "motivacion": seleccion.descripcion,
    }


def _construir_payload_servicios_requeridos(
    *,
    id_inspeccion: uuid.UUID,
    resultado: LevantamientoFinalizeResult,
    body: LevantamientoRequest,
    translator: ServiciosRequeridosTranslator,
) -> dict[str, Any] | None:
    """Arma el payload de servicios_requeridos para ms-requerimientos, o None si no hay
    nada que reportar (el inspector no marcó servicios ni inspección técnica) o si falta
    algún dato que el webhook necesita (coordenadas ausentes/ilegibles)."""
    servicios: list[dict[str, Any]] = [
        _traducir_seleccion(tipo, seleccion, translator)
        for tipo, selecciones in (body.servicios_requeridos or {}).items()
        for seleccion in selecciones
    ]

    if body.inspeccion_tecnica_req:
        servicios.extend(
            _traducir_seleccion("INSPECCION_TECNICA", seleccion, translator)
            for seleccion in body.tipos_inspeccion_tecnica or []
        )

    if not servicios:
        logger.info(
            "Levantamiento sin servicios_requeridos ni inspección técnica; se omite el "
            "webhook de ms-requerimientos",
            extra={
                "event": "ordenes_servicio_webhook_sin_servicios",
                "id_inspeccion": str(id_inspeccion),
            },
        )
        return None

    coordenadas = _parsear_coordenadas(body.coordenadas)
    if coordenadas is None:
        logger.warning(
            "No se pudo leer coordenadas del levantamiento; se omite el webhook de "
            "ms-requerimientos",
            extra={
                "event": "ordenes_servicio_webhook_sin_coordenadas",
                "id_inspeccion": str(id_inspeccion),
            },
        )
        return None
    latitud, longitud = coordenadas

    return {
        "inspeccion_id": str(id_inspeccion),
        "numero_inspeccion": (
            str(resultado.numero_inspeccion) if resultado.numero_inspeccion is not None else None
        ),
        "id_bien_inventario": (
            str(resultado.id_bien_inventario) if resultado.id_bien_inventario else None
        ),
        # Solo tenemos la fecha del levantamiento, sin hora: se envía medianoche UTC como
        # marcador de posición hasta confirmar con ms-requerimientos si aceptan solo fecha.
        "fecha_inspeccion": f"{body.fecha_levantamiento.isoformat()}T00:00:00Z",
        "latitud_inspeccion": latitud,
        "longitud_inspeccion": longitud,
        "servicios_requeridos": servicios,
    }


# ------------------------------------------------------------------
# Utilidad: await varios coroutines en paralelo
# ------------------------------------------------------------------

import asyncio  # noqa: E402


async def _gather(*coros: Any) -> tuple[Any, ...]:  # type: ignore[return]
    return tuple(await asyncio.gather(*coros))


def _to_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


def _normalize_numero_finca(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_numeros_finca(
    raw_values: Any,
    fallback_value: Any,
) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []

    if isinstance(raw_values, list):
        candidates = raw_values
    elif raw_values is None:
        candidates = []
    else:
        candidates = [raw_values]

    for candidate in candidates:
        numero = _normalize_numero_finca(candidate)
        if numero is None or numero in seen:
            continue
        seen.add(numero)
        values.append(numero)

    if values:
        return values

    fallback = _normalize_numero_finca(fallback_value)
    return [fallback] if fallback is not None else []
