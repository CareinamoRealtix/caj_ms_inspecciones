"""Routers de inspecciones — todos los endpoints del módulo."""
from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import date
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from app.application.gestion_catalogos import AlertaGestion
from app.application.inspeccion_service import (
    CodigoCatalogoInvalidoError,
    GestionDateFiltersError,
    GestionLocationFiltersError,
    InspeccionActivaExistenteError,
    InspeccionAlreadyFinalizedError,
    InspeccionNotFoundError,
    InspeccionService,
    LevantamientoOperacionConflictoError,
    PeriodicidadNotFoundError,
)
from app.application.inspectores import build_inspector_items
from app.infrastructure.clients.azure_ad_client import AzureAdClient, AzureAdError
from app.presentation.api.dependencies.inspecciones import (
    get_azure_ad_client,
    get_current_user_email,
    get_inspeccion_service,
    require_direct_levantamiento_habilitado,
)
from app.presentation.api.schemas.inspecciones import (
    CatalogoResponse,
    ControlResponse,
    DetalleInspeccionResponse,
    FormularioBatchCreateRequest,
    FormularioBatchCreateResponse,
    FormularioCatalogosResponse,
    FormularioCreateRequest,
    FormularioCreateResponse,
    FormularioDetailResponse,
    FormularioUpdateRequest,
    FotografiasInspeccionResponse,
    FotografiasUpdateRequest,
    FotografiasUpdateResponse,
    GestionCatalogosResponse,
    GestionResponse,
    HistoricoResponse,
    LevantamientoBatchRequest,
    LevantamientoBatchResponse,
    LevantamientoCatalogosResponse,
    LevantamientoRequest,
    LevantamientoResponse,
    SincronizacionResponse,
)
from app.presentation.pdf.inspeccion_pdf import generar_pdf_inspeccion

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Inspecciones"])


# ---------------------------------------------------------------------------
# Catálogos y utilidades
# ---------------------------------------------------------------------------


@router.get("/catalogo", response_model=CatalogoResponse)
async def get_catalogo(
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
) -> CatalogoResponse:
    """Retorna todos los catálogos necesarios para los formularios."""
    return await svc.get_catalogo()


# ---------------------------------------------------------------------------
# Gestión (vista consolidada + enrich de inspecciones)
# ---------------------------------------------------------------------------


@router.get("/gestion/catalogos", response_model=GestionCatalogosResponse)
async def get_catalogos_gestion(
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    azure_client: Annotated[AzureAdClient, Depends(get_azure_ad_client)],
) -> GestionCatalogosResponse:
    """Retorna las opciones de los filtros superiores de la pantalla de gestión."""
    try:
        members = await azure_client.get_inspectores()
    except AzureAdError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    finally:
        await azure_client.aclose()

    return await svc.get_catalogos_gestion(build_inspector_items(members))


@router.get("/gestion", response_model=GestionResponse)
async def get_gestion(
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    pagina: int = Query(default=1, ge=1),
    tamanio: int = Query(default=15, ge=1, le=100),
    numero_finca: str | None = Query(default=None),
    estatus_bien_inventario: int | None = Query(default=None, ge=1),
    provincia: int | None = Query(default=None, ge=1),
    distrito: int | None = Query(default=None, ge=1),
    corregimiento: int | None = Query(default=None, ge=1),
    nuevo_ingreso: bool = Query(default=False),
    alerta: AlertaGestion | None = Query(default=None),
    ruta: uuid.UUID | None = Query(default=None),
    inspector: str | None = Query(default=None),
    month_last_insp: int | None = Query(default=None, ge=1, le=12),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
) -> GestionResponse:
    """Lista todos los bienes del inventario con su estado de inspección activa."""
    try:
        return await svc.get_gestion(
            pagina=pagina,
            tamanio=tamanio,
            numero_finca=numero_finca,
            estatus_bien_inventario=estatus_bien_inventario,
            provincia=provincia,
            distrito=distrito,
            corregimiento=corregimiento,
            nuevo_ingreso=nuevo_ingreso,
            alerta=alerta,
            ruta=ruta,
            inspector=inspector,
            month_last_insp=month_last_insp,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
    except GestionLocationFiltersError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except GestionDateFiltersError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/control", response_model=ControlResponse)
async def get_control(
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    pagina: int = Query(default=1, ge=1),
    tamanio: int = Query(default=15, ge=1, le=100),
    numero_finca: str | None = Query(default=None),
    estatus_bien_inventario: int | None = Query(default=None, ge=1),
    provincia: int | None = Query(default=None, ge=1),
    distrito: int | None = Query(default=None, ge=1),
    corregimiento: int | None = Query(default=None, ge=1),
    alerta: AlertaGestion | None = Query(default=None),
    inspector: str | None = Query(default=None),
    month_expiration: int | None = Query(default=None, ge=1, le=12),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
) -> ControlResponse:
    """Lista bienes para control usando los filtros aplicables a inspecciones."""
    try:
        return await svc.get_control(
            pagina=pagina,
            tamanio=tamanio,
            numero_finca=numero_finca,
            estatus_bien_inventario=estatus_bien_inventario,
            provincia=provincia,
            distrito=distrito,
            corregimiento=corregimiento,
            alerta=alerta,
            inspector=inspector,
            month_expiration=month_expiration,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
    except GestionLocationFiltersError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except GestionDateFiltersError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# CRUD de inspección
# ---------------------------------------------------------------------------


@router.get("/formulario/catalogos", response_model=FormularioCatalogosResponse)
async def get_catalogos_formulario(
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    azure_client: Annotated[AzureAdClient, Depends(get_azure_ad_client)],
) -> FormularioCatalogosResponse:
    """Retorna las opciones de los selectores del modal de programación."""
    try:
        members = await azure_client.get_inspectores()
    except AzureAdError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    finally:
        await azure_client.aclose()

    return await svc.get_catalogos_formulario(build_inspector_items(members))


@router.get("/levantamiento/catalogos", response_model=LevantamientoCatalogosResponse)
async def get_catalogos_levantamiento(
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
) -> LevantamientoCatalogosResponse:
    """Catálogo de opciones del formulario de levantamiento (HU 8). No depende del flag directo."""
    return await svc.get_catalogos_levantamiento()


@router.post(
    "/formulario",
    response_model=FormularioCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_inspeccion(
    body: FormularioCreateRequest,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    usuario: Annotated[str | None, Depends(get_current_user_email)],
) -> FormularioCreateResponse:
    """Programa una nueva inspección para un bien."""
    try:
        return await svc.crear_inspeccion(body, creado_por=usuario)
    except PeriodicidadNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La periodicidad seleccionada no existe",
        ) from exc
    except InspeccionActivaExistenteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/formulario/batch",
    response_model=FormularioBatchCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_inspecciones_batch(
    body: FormularioBatchCreateRequest,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    usuario: Annotated[str | None, Depends(get_current_user_email)],
) -> FormularioBatchCreateResponse:
    """Programa inspecciones para varios bienes con una asignación común."""
    try:
        return await svc.crear_inspecciones_batch(body, creado_por=usuario)
    except PeriodicidadNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La periodicidad seleccionada no existe",
        ) from exc


@router.get("/formulario/{id_inspeccion}", response_model=FormularioDetailResponse)
async def get_formulario(
    id_inspeccion: uuid.UUID,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
) -> FormularioDetailResponse:
    """Precarga los datos de una inspección para el formulario de reprogramación."""
    try:
        return await svc.get_formulario(id_inspeccion)
    except InspeccionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Inspección no encontrada"
        ) from exc


@router.put("/formulario/{id_inspeccion}", response_model=FormularioCreateResponse)
async def reprogramar_inspeccion(
    id_inspeccion: uuid.UUID,
    body: FormularioCreateRequest,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    usuario: Annotated[str | None, Depends(get_current_user_email)],
) -> FormularioCreateResponse:
    """Reprograma una inspección existente."""
    try:
        return await svc.reprogramar_inspeccion(id_inspeccion, body, modificado_por=usuario)
    except InspeccionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Inspección no encontrada"
        ) from exc
    except InspeccionAlreadyFinalizedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No se puede reprogramar una inspección finalizada",
        ) from exc
    except PeriodicidadNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La periodicidad seleccionada no existe",
        ) from exc


@router.patch("/formulario/{id_inspeccion}", response_model=FormularioCreateResponse)
async def editar_inspeccion(
    id_inspeccion: uuid.UUID,
    body: FormularioUpdateRequest,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    usuario: Annotated[str | None, Depends(get_current_user_email)],
) -> FormularioCreateResponse:
    """Edita una inspección no finalizada sin cambiar su bien ni número de finca."""
    try:
        return await svc.editar_inspeccion(id_inspeccion, body, modificado_por=usuario)
    except InspeccionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Inspección no encontrada"
        ) from exc
    except InspeccionAlreadyFinalizedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No se puede editar una inspección finalizada",
        ) from exc
    except PeriodicidadNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La periodicidad seleccionada no existe",
        ) from exc


# ---------------------------------------------------------------------------
# Histórico
# ---------------------------------------------------------------------------


@router.get("/historico", response_model=HistoricoResponse)
async def get_historico(
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    numero_finca: str | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamanio: int = Query(default=15, ge=1, le=100),
    provincia: int | None = Query(default=None, ge=1),
    distrito: int | None = Query(default=None, ge=1),
    corregimiento: int | None = Query(default=None, ge=1),
    ruta: uuid.UUID | None = Query(default=None),
    inspector: str | None = Query(default=None),
    month_last_insp: int | None = Query(default=None, ge=1, le=12),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
) -> HistoricoResponse:
    """Lista el histórico de inspecciones finalizadas.

    Todos los filtros son opcionales y combinables; `numero_finca` busca por texto
    parcial. Sin ningún filtro no se devuelve ningún dato.
    """
    try:
        return await svc.get_historico(
            numero_finca=numero_finca,
            pagina=pagina,
            tamanio=tamanio,
            provincia=provincia,
            distrito=distrito,
            corregimiento=corregimiento,
            ruta=ruta,
            inspector=inspector,
            month_last_insp=month_last_insp,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
    except GestionLocationFiltersError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except GestionDateFiltersError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# Sincronización offline (HU.12) — endpoint provisional
# ---------------------------------------------------------------------------


@router.get("/sincronizacion", response_model=SincronizacionResponse)
async def get_sincronizacion(
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    email_inspector: str = Query(...),
) -> SincronizacionResponse:
    """Sustituto provisional del job de AWS Batch (ver sincronizacion-diseno-json.md).

    Devuelve, para el inspector indicado, las inspecciones programadas desde hoy en adelante con la
    vista de finca y el precargue del último levantamiento finalizado, más los catálogos
    necesarios para diligenciarlas offline. No incluye fotografías ni rutas óptimas
    (placeholder vacío, HU.11 pendiente de definir).
    """
    return await svc.get_sincronizacion(email_inspector)


# ---------------------------------------------------------------------------
# Detalle completo, fotos y PDF
# ---------------------------------------------------------------------------


@router.get("/{id_inspeccion}/detalle", response_model=DetalleInspeccionResponse)
async def get_detalle(
    id_inspeccion: uuid.UUID,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
) -> DetalleInspeccionResponse:
    """Vista consolidada con levantamiento y fotografías."""
    try:
        return await svc.get_detalle(id_inspeccion)
    except InspeccionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Inspección no encontrada"
        ) from exc


@router.get("/{id_inspeccion}/fotografias", response_model=FotografiasInspeccionResponse)
async def get_fotografias(
    id_inspeccion: uuid.UUID,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
) -> FotografiasInspeccionResponse:
    """Catálogo de fotografías de la inspección, para seleccionar principal/visibles."""
    try:
        return await svc.get_fotografias(id_inspeccion)
    except InspeccionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Inspección no encontrada"
        ) from exc


@router.patch("/{id_inspeccion}/fotografias", response_model=FotografiasUpdateResponse)
async def update_fotografias(
    id_inspeccion: uuid.UUID,
    body: FotografiasUpdateRequest,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
) -> FotografiasUpdateResponse:
    """Actualiza visibilidad geovisor y foto principal."""
    await svc.update_fotografias(id_inspeccion, body.fotografias)
    return FotografiasUpdateResponse()


async def _resolver_nombre_inspector(
    email_inspector: str, azure_client: AzureAdClient
) -> str:
    """Resuelve el displayName del inspector en Entra ID; usa el correo si falla."""
    try:
        miembros = await azure_client.get_inspectores()
    except AzureAdError:
        logger.warning(
            "No se pudo resolver el nombre del inspector para el PDF",
            extra={"event": "pdf_resolver_inspector_failed"},
        )
        return email_inspector
    finally:
        await azure_client.aclose()

    por_correo = {
        (m.get("mail") or m.get("userPrincipalName") or "").lower(): m.get("displayName")
        for m in miembros
    }
    return por_correo.get(email_inspector.lower()) or email_inspector


async def _descargar(url: str, client: httpx.AsyncClient) -> bytes | None:
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.content
    except (httpx.RequestError, httpx.HTTPStatusError):
        logger.warning(
            "No se pudo descargar una imagen para el PDF de inspección",
            extra={"event": "pdf_descarga_imagen_failed"},
        )
        return None


@router.get("/{id_inspeccion}/pdf")
async def get_pdf(
    id_inspeccion: uuid.UUID,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    azure_client: Annotated[AzureAdClient, Depends(get_azure_ad_client)],
) -> StreamingResponse:
    """Genera y descarga el informe PDF de la inspección."""
    try:
        detalle = await svc.get_detalle(id_inspeccion)
    except InspeccionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Inspección no encontrada"
        ) from exc

    catalogos_response = await svc.get_catalogos_levantamiento()
    inspector_nombre = await _resolver_nombre_inspector(detalle.email_inspector, azure_client)

    fotos_bytes: dict[uuid.UUID, bytes | None] = {}
    firma_bytes: bytes | None = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        urls = [(f.id_fotografia, f.url_s3) for f in detalle.fotografias]
        descargas = await asyncio.gather(*(_descargar(url, client) for _, url in urls))
        fotos_bytes = dict(zip((id_foto for id_foto, _ in urls), descargas, strict=True))

        if detalle.levantamiento and detalle.levantamiento.url_firma_inspector:
            firma_bytes = await _descargar(detalle.levantamiento.url_firma_inspector, client)

    pdf_bytes = generar_pdf_inspeccion(
        detalle,
        catalogos_response.catalogos,
        inspector_nombre=inspector_nombre,
        fotos_bytes=fotos_bytes,
        firma_bytes=firma_bytes,
    )
    filename = f"inspeccion_{detalle.numero_inspeccion}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Levantamiento
# ---------------------------------------------------------------------------


@router.post(
    "/{id_inspeccion}/levantamiento",
    response_model=LevantamientoResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_direct_levantamiento_habilitado)],
)
async def finalizar_levantamiento(
    id_inspeccion: uuid.UUID,
    body: LevantamientoRequest,
    response: Response,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    usuario: Annotated[str | None, Depends(get_current_user_email)],
) -> LevantamientoResponse:
    """Finaliza el levantamiento de campo. Solo acepta información completa (sin borradores)."""
    try:
        resultado, repetido = await svc.finalizar_levantamiento(
            id_inspeccion, body, usuario=usuario
        )
    except InspeccionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Inspección no encontrada"
        ) from exc
    except LevantamientoOperacionConflictoError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CodigoCatalogoInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    if repetido:
        response.status_code = status.HTTP_200_OK
    return resultado


@router.post(
    "/levantamiento/batch",
    response_model=LevantamientoBatchResponse,
    dependencies=[Depends(require_direct_levantamiento_habilitado)],
)
async def finalizar_levantamientos_batch(
    body: LevantamientoBatchRequest,
    svc: Annotated[InspeccionService, Depends(get_inspeccion_service)],
    usuario: Annotated[str | None, Depends(get_current_user_email)],
) -> LevantamientoBatchResponse:
    """Finaliza el levantamiento de campo de varias inspecciones en un solo llamado.

    Cada ítem se procesa con la misma lógica y las mismas consecuencias que
    POST /{id_inspeccion}/levantamiento (validación de catálogos, idempotencia por
    id_operacion, fotografías, webhook a ms-requerimientos). Un ítem inválido o en
    conflicto no aborta el lote: queda reportado como fallido en `resultados` y el
    resto se procesa igual.
    """
    return await svc.finalizar_levantamiento_batch(body, usuario=usuario)
