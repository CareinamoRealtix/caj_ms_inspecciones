from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.presentation.api.schemas.inspectores import InspectorItem

# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------


class TipoInspeccionOut(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    permite_descripcion_libre: bool


class PeriodicidadOut(BaseModel):
    id: int
    nombre: str
    dias_vigencia: int


class CatalogoResponse(BaseModel):
    tipos_inspeccion: list[TipoInspeccionOut]
    periodicidades: list[PeriodicidadOut]


class RutaOut(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str


class FormularioCatalogosResponse(BaseModel):
    rutas: list[RutaOut]
    inspectores: list[InspectorItem]
    tipos_inspeccion: list[TipoInspeccionOut]
    periodicidades: list[PeriodicidadOut]


# ---------------------------------------------------------------------------
# Crear / actualizar inspección
# ---------------------------------------------------------------------------


class FormularioCreateRequest(BaseModel):
    id_bien_inventario: uuid.UUID
    numero_finca: str
    ruta_id: uuid.UUID
    ruta_nombre: str = Field(min_length=1, max_length=255)
    id_tipo_inspeccion: int
    descripcion_tipo: str | None = Field(default=None, max_length=255)
    email_inspector: str = Field(max_length=150)
    id_periodicidad: int = Field(gt=0)
    fecha_programada: date

    @field_validator("ruta_nombre", mode="before")
    @classmethod
    def normalizar_ruta(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class FormularioCreateResponse(BaseModel):
    id_inspeccion: uuid.UUID
    numero_inspeccion: int


class FormularioUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ruta_id: uuid.UUID
    ruta_nombre: str = Field(min_length=1, max_length=255)
    id_tipo_inspeccion: int
    descripcion_tipo: str | None = Field(default=None, max_length=255)
    email_inspector: str = Field(max_length=150)
    id_periodicidad: int = Field(gt=0)
    fecha_programada: date

    @field_validator("ruta_nombre", mode="before")
    @classmethod
    def normalizar_ruta(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class BienFormularioBatchRequest(BaseModel):
    id_bien_inventario: uuid.UUID
    numero_finca: str


class FormularioBatchCreateRequest(BaseModel):
    bienes: list[BienFormularioBatchRequest] = Field(min_length=1)
    ruta_id: uuid.UUID
    ruta_nombre: str = Field(min_length=1, max_length=255)
    id_tipo_inspeccion: int
    descripcion_tipo: str | None = Field(default=None, max_length=255)
    email_inspector: str = Field(max_length=150)
    id_periodicidad: int = Field(gt=0)
    fecha_programada: date

    @field_validator("ruta_nombre", mode="before")
    @classmethod
    def normalizar_ruta(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("bienes")
    @classmethod
    def validar_bienes_unicos(
        cls, bienes: list[BienFormularioBatchRequest]
    ) -> list[BienFormularioBatchRequest]:
        # Allow the same `id_bien_inventario` multiple times only when the
        # `numero_finca` differs. Reject exact duplicate pairs.
        seen: set[tuple[uuid.UUID, str]] = set()
        for bien in bienes:
            key = (bien.id_bien_inventario, bien.numero_finca)
            if key in seen:
                raise ValueError("No se permiten bienes duplicados en el lote")
            seen.add(key)
        return bienes


class FormularioBatchItemResponse(FormularioCreateResponse):
    id_bien_inventario: uuid.UUID
    numero_finca: str


class FormularioBatchCreateResponse(BaseModel):
    total_creadas: int
    inspecciones: list[FormularioBatchItemResponse]


# ---------------------------------------------------------------------------
# Detalle de formulario (GET /formulario/{id})
# ---------------------------------------------------------------------------


class FormularioDetailResponse(BaseModel):
    id_inspeccion: uuid.UUID
    numero_inspeccion: int
    id_bien_inventario: uuid.UUID
    numero_finca: str
    ruta_id: uuid.UUID
    ruta_nombre: str
    id_tipo_inspeccion: int
    tipo_inspeccion: str
    descripcion_tipo: str | None
    email_inspector: str
    estado_inspeccion: str
    id_periodicidad: int | None
    periodicidad: str | None
    dias_vigencia: int | None
    fecha_programada: date
    fecha_realizada: date | None
    fecha_vencimiento: date | None
    origen: str
    activa: bool
    creado_por: str | None
    fecha_creacion: datetime


# ---------------------------------------------------------------------------
# Gestión (inventario desde vista + enrich de inspecciones)
# ---------------------------------------------------------------------------


class GestionItemResponse(BaseModel):
    id_bien_inventario: uuid.UUID
    id_bien: uuid.UUID | None
    no_registro: int
    numero_finca: str | None
    numeros_finca: list[str]
    nombre_deudor: str | None
    numero_prestamo: str | None
    id_tipo_propiedad: int | None
    tipo_propiedad: str | None
    id_provincia: int | None
    provincia: str | None
    id_distrito: int | None
    distrito: str | None
    id_corregimiento: int | None
    corregimiento: str | None
    barriada_sector: str | None
    direccion: str | None
    numero_lote: str | None
    latitud: float | None
    longitud: float | None
    url_ubicacion_geoespacial: str | None
    monto_adjudicado: Decimal | None
    valor_avaluo: Decimal | None
    estatus_bien: str | None
    color_badge: str | None
    estado_inventario: str | None
    oficinista: str | None
    usuario_registrador: str | None
    fecha_recibido_inventario: date | None
    fecha_creacion: datetime | None
    ruta_id: uuid.UUID | None
    ruta_nombre: str | None
    inspeccion_ruta_id: uuid.UUID | None
    inspeccion_ruta_nombre: str | None
    inspeccion_email_inspector: str | None
    inspeccion_id_periodicidad: int | None
    inspeccion_periodicidad: str | None
    inspeccion_tipo_inspeccion: str | None
    inspeccion_descripcion_tipo: str | None
    tiene_inspeccion_activa: bool
    id_inspeccion: uuid.UUID | None
    numero_inspeccion: str | None = None
    estado_inspeccion: str | None
    color_badge_inspeccion: str | None
    fecha_programada: date | None
    fecha_realizada: date | None
    fecha_vencimiento: date | None
    estado_alerta: Literal["VENCIDA", "PROXIMA", "TERMINO"] | None = None
    color_alerta: str | None = None


class GestionResponse(BaseModel):
    data: list[GestionItemResponse]
    pagina: int
    tamanio: int
    total_registros: int
    total_paginas: int


class ControlItemResponse(GestionItemResponse):
    numero_inspeccion: str | None = None
    estado_inspeccion: Literal["VENCIDA", "PROXIMA", "TERMINO"] | None


class ControlResponse(GestionResponse):
    data: list[ControlItemResponse]


class HistoricoItemResponse(BaseModel):
    id_inspeccion: uuid.UUID
    id_bien_inventario: uuid.UUID
    numero_finca: str
    numero_inspeccion: str | None
    email_inspector: str
    fecha_programada: date
    fecha_realizada: date | None
    fecha_vencimiento: date | None
    fecha_creacion: datetime
    fecha_modificacion: datetime | None
    activa: bool
    estado_inspeccion: str


class HistoricoResponse(BaseModel):
    data: list[HistoricoItemResponse]
    pagina: int
    tamanio: int
    total_registros: int
    total_paginas: int


class CatalogoGestionItem(BaseModel):
    id: int
    nombre: str


class EstatusBienInventarioGestionItem(BaseModel):
    id: int
    estado: str


class DistritoGestionItem(CatalogoGestionItem):
    id_provincia: int


class CorregimientoGestionItem(CatalogoGestionItem):
    id_distrito: int


class GestionCatalogosResponse(BaseModel):
    inspectores: list[InspectorItem]
    estatus_bien_inventario: list[EstatusBienInventarioGestionItem]
    alertas: list[str]
    provincias: list[CatalogoGestionItem]
    distritos: list[DistritoGestionItem]
    corregimientos: list[CorregimientoGestionItem]
    rutas: list[RutaOut]


# ---------------------------------------------------------------------------
# Detalle completo (con levantamiento y fotos)
# ---------------------------------------------------------------------------


class OcupanteDetail(BaseModel):
    nombre: str | None
    tipo_identificacion: str | None
    numero_identificacion: str | None
    numero_contacto: str | None
    comentarios: str | None


GRUPOS_SERVICIOS_REQUERIDOS = ("LIMPIEZA", "CERRAJERIA_MATERIAL", "REPARACION")


class SeleccionOpcion(BaseModel):
    codigo: str = Field(min_length=1, max_length=50)
    cantidad: int | None = Field(default=None, gt=0)
    descripcion: str | None = Field(default=None, max_length=500)


def _validar_sin_duplicados(valores: list[SeleccionOpcion]) -> list[SeleccionOpcion]:
    codigos = [v.codigo for v in valores]
    if len(codigos) != len(set(codigos)):
        raise ValueError("No se permiten códigos duplicados dentro del mismo grupo")
    return valores


def _validar_puertas_sin_duplicados(
    valor: dict[str, list[SeleccionOpcion]],
) -> dict[str, list[SeleccionOpcion]]:
    for opciones in valor.values():
        _validar_sin_duplicados(opciones)
    return valor


class LevantamientoDetail(BaseModel):
    coordenadas: str | None
    condicion_bien: str
    estado_ocupacion: str
    ocupante: OcupanteDetail
    puertas: dict[str, list[SeleccionOpcion]] | None
    tipos_ventanas: list[SeleccionOpcion] | None
    servicios_publicos: list[SeleccionOpcion] | None
    distribucion_inmueble: list[SeleccionOpcion] | None
    servicios_requeridos: dict[str, list[SeleccionOpcion]] | None
    inspeccion_tecnica_req: bool
    tipos_inspeccion_tecnica: list[SeleccionOpcion] | None
    motivacion: str | None
    url_firma_inspector: str | None
    observaciones: str | None
    fecha_levantamiento: date


class FotografiaDetail(BaseModel):
    id_fotografia: uuid.UUID
    url_s3: str
    nombre_archivo: str | None
    es_visible_geovisor: bool
    es_foto_principal: bool
    orden: int


class FotografiasInspeccionResponse(BaseModel):
    id_inspeccion: uuid.UUID
    fotografias: list[FotografiaDetail]


class DetalleInspeccionResponse(BaseModel):
    id_inspeccion: uuid.UUID
    numero_inspeccion: int
    numero_finca: str
    id_bien_inventario: uuid.UUID
    ruta_id: uuid.UUID
    ruta_nombre: str
    fecha_programada: date
    fecha_realizada: date | None
    tipo_inspeccion: str
    descripcion_tipo: str | None
    email_inspector: str
    estado_inspeccion: str
    color_badge: str | None
    origen: str
    provincia: str | None
    distrito: str | None
    corregimiento: str | None
    barriada_sector: str | None
    direccion: str | None
    numero_lote: str | None
    levantamiento: LevantamientoDetail | None
    fotografias: list[FotografiaDetail]


# ---------------------------------------------------------------------------
# Fotografías PATCH
# ---------------------------------------------------------------------------


class FotografiaUpdate(BaseModel):
    id_fotografia: uuid.UUID
    es_visible_geovisor: bool
    es_foto_principal: bool


class FotografiasUpdateRequest(BaseModel):
    fotografias: list[FotografiaUpdate]

    @field_validator("fotografias")
    @classmethod
    def una_sola_principal(cls, v: list[FotografiaUpdate]) -> list[FotografiaUpdate]:
        principales = [f for f in v if f.es_foto_principal]
        if len(principales) > 1:
            raise ValueError("Solo una fotografía puede ser la principal")
        return v


class FotografiasUpdateResponse(BaseModel):
    mensaje: str = "Fotografías actualizadas correctamente"


# ---------------------------------------------------------------------------
# Levantamiento
# ---------------------------------------------------------------------------


class FotografiaLevantamientoRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    nombre_archivo: str | None = Field(default=None, max_length=255)
    es_visible_geovisor: bool = False
    es_foto_principal: bool = False
    orden: int | None = Field(default=None, ge=0)

    @field_validator("url")
    @classmethod
    def validar_esquema_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://", "fotos/", "firmas/")):
            raise ValueError("url debe ser http(s):// o una clave S3 (fotos/..., firmas/...)")
        return v


class LevantamientoRequest(BaseModel):
    id_operacion: uuid.UUID
    coordenadas: str | None = None
    condicion_bien: str = Field(max_length=50)
    estado_ocupacion: str = Field(max_length=50)
    nombre_ocupante: str | None = Field(default=None, max_length=200)
    tipo_identificacion_ocup: str | None = Field(default=None, max_length=50)
    numero_identificacion_ocup: str | None = Field(default=None, max_length=50)
    numero_contacto_ocupante: str | None = Field(default=None, max_length=50)
    comentarios_ocupante: str | None = Field(default=None, max_length=500)
    puertas: dict[str, list[SeleccionOpcion]] | None = None
    tipos_ventanas: list[SeleccionOpcion] | None = None
    servicios_publicos: list[SeleccionOpcion] | None = None
    distribucion_inmueble: list[SeleccionOpcion] | None = None
    servicios_requeridos: dict[str, list[SeleccionOpcion]] | None = None
    inspeccion_tecnica_req: bool = False
    tipos_inspeccion_tecnica: list[SeleccionOpcion] | None = None
    motivacion: str | None = None
    url_firma_inspector: str | None = Field(default=None, max_length=500)
    observaciones: str | None = None
    fecha_levantamiento: date
    fotografias: list[FotografiaLevantamientoRequest] = Field(default_factory=list)

    @field_validator("coordenadas")
    @classmethod
    def validar_coordenadas(cls, v: str | None) -> str | None:
        """Formato "lat,lng" en grados decimales (WGS84, SRID 4326)."""
        if v is None:
            return v
        partes = v.split(",")
        try:
            if len(partes) != 2:
                raise ValueError
            latitud, longitud = float(partes[0]), float(partes[1])
        except ValueError:
            raise ValueError('coordenadas debe tener el formato "latitud,longitud"') from None
        if not (-90 <= latitud <= 90 and -180 <= longitud <= 180):
            raise ValueError("coordenadas fuera de rango (latitud ±90, longitud ±180)")
        return v

    @field_validator(
        "tipos_ventanas",
        "servicios_publicos",
        "distribucion_inmueble",
        "tipos_inspeccion_tecnica",
    )
    @classmethod
    def validar_listas_sin_duplicados(
        cls, v: list[SeleccionOpcion] | None
    ) -> list[SeleccionOpcion] | None:
        return v if v is None else _validar_sin_duplicados(v)

    @field_validator("servicios_requeridos")
    @classmethod
    def validar_servicios_requeridos_agrupados(
        cls, v: dict[str, list[SeleccionOpcion]] | None
    ) -> dict[str, list[SeleccionOpcion]] | None:
        if v is None:
            return v
        invalidos = sorted(set(v) - set(GRUPOS_SERVICIOS_REQUERIDOS))
        if invalidos:
            raise ValueError(
                f"Grupos no permitidos en servicios_requeridos: {', '.join(invalidos)}. "
                f"Permitidos: {', '.join(GRUPOS_SERVICIOS_REQUERIDOS)}"
            )
        return _validar_puertas_sin_duplicados(v)

    @field_validator("puertas")
    @classmethod
    def validar_puertas_sin_duplicados(
        cls, v: dict[str, list[SeleccionOpcion]] | None
    ) -> dict[str, list[SeleccionOpcion]] | None:
        return v if v is None else _validar_puertas_sin_duplicados(v)

    @field_validator("fotografias")
    @classmethod
    def validar_fotografias_una_sola_principal(
        cls, v: list[FotografiaLevantamientoRequest]
    ) -> list[FotografiaLevantamientoRequest]:
        principales = [f for f in v if f.es_foto_principal]
        if len(principales) > 1:
            raise ValueError("Solo una fotografía puede ser la principal")
        return v

    @model_validator(mode="after")
    def validar_ocupante(self) -> LevantamientoRequest:
        if self.estado_ocupacion in ("OCUPADO", "PARCIALMENTE_OCUPADO", "INVADIDO"):
            if not self.nombre_ocupante or not self.numero_contacto_ocupante:
                raise ValueError(
                    "nombre_ocupante y numero_contacto_ocupante son requeridos cuando "
                    "estado_ocupacion es OCUPADO, PARCIALMENTE_OCUPADO o INVADIDO"
                )
        return self


class LevantamientoResponse(BaseModel):
    id_levantamiento: uuid.UUID
    id_inspeccion: uuid.UUID
    estado_inspeccion: str
    mensaje: str


class LevantamientoBatchItemRequest(LevantamientoRequest):
    id_inspeccion: uuid.UUID


class LevantamientoBatchRequest(BaseModel):
    levantamientos: list[LevantamientoBatchItemRequest] = Field(min_length=1)

    @field_validator("levantamientos")
    @classmethod
    def validar_inspecciones_unicas(
        cls, levantamientos: list[LevantamientoBatchItemRequest]
    ) -> list[LevantamientoBatchItemRequest]:
        vistos: set[uuid.UUID] = set()
        for item in levantamientos:
            if item.id_inspeccion in vistos:
                raise ValueError(f"id_inspeccion {item.id_inspeccion} está repetido en el lote")
            vistos.add(item.id_inspeccion)
        return levantamientos


CodigoErrorLevantamientoBatch = Literal[
    "no_encontrada",
    "contenido_diferente",
    "ya_finalizada",
    "otra_inspeccion",
    "codigo_catalogo_invalido",
]


class LevantamientoBatchItemResult(BaseModel):
    id_inspeccion: uuid.UUID
    exito: bool
    repetido: bool = False
    id_levantamiento: uuid.UUID | None = None
    estado_inspeccion: str | None = None
    mensaje: str | None = None
    codigo_error: CodigoErrorLevantamientoBatch | None = None


class LevantamientoBatchResponse(BaseModel):
    total: int
    exitosos: int
    fallidos: int
    resultados: list[LevantamientoBatchItemResult]


class LevantamientoOpcionOut(BaseModel):
    codigo: str
    nombre: str
    requiere_cantidad: bool
    permite_descripcion: bool
    orden: int


class LevantamientoCatalogosResponse(BaseModel):
    version: datetime
    catalogos: dict[str, list[LevantamientoOpcionOut]]


# ---------------------------------------------------------------------------
# Sincronización offline (HU.12) — endpoint provisional
# ---------------------------------------------------------------------------


class SincronizacionCatalogoItem(BaseModel):
    id: int
    nombre: str


class SincronizacionDistritoItem(SincronizacionCatalogoItem):
    id_provincia: int


class SincronizacionCorregimientoItem(SincronizacionCatalogoItem):
    id_distrito: int


class SincronizacionCatalogosInventarioOut(BaseModel):
    estatus_bien_inventario: list[SincronizacionCatalogoItem]
    provincias: list[SincronizacionCatalogoItem]
    distritos: list[SincronizacionDistritoItem]
    corregimientos: list[SincronizacionCorregimientoItem]


class SincronizacionCatalogosOut(BaseModel):
    version: datetime
    tipos_inspeccion: list[TipoInspeccionOut]
    periodicidades: list[PeriodicidadOut]
    rutas: list[RutaOut]
    levantamiento_opciones: dict[str, list[LevantamientoOpcionOut]]
    catalogos_inventario: SincronizacionCatalogosInventarioOut


class SincronizacionFincaOut(BaseModel):
    id_bien_inventario: uuid.UUID
    id_bien: uuid.UUID | None
    numero_finca: str
    numeros_finca: list[str]
    nombre_deudor: str | None
    numero_prestamo: str | None
    tipo_propiedad: str | None
    direccion: str | None
    provincia: str | None
    distrito: str | None
    corregimiento: str | None
    barriada_sector: str | None
    numero_lote: str | None
    latitud: float | None
    longitud: float | None
    url_ubicacion_geoespacial: str | None
    id_estatus_bien: int | None
    estatus_bien: str | None
    color_badge: str | None
    id_estado_inventario: int | None
    estado_inventario: str | None


class SincronizacionUltimoLevantamientoOut(BaseModel):
    id_inspeccion: uuid.UUID
    numero_inspeccion: int
    fecha_levantamiento: date
    coordenadas: str | None
    condicion_bien: str | None
    estado_ocupacion: str | None
    nombre_ocupante: str | None
    ocupante: OcupanteDetail
    puertas: dict[str, list[SeleccionOpcion]] | None
    tipos_ventanas: list[SeleccionOpcion] | None
    distribucion_inmueble: list[SeleccionOpcion] | None
    servicios_publicos: list[SeleccionOpcion] | None
    observaciones: str | None


class SincronizacionInspeccionOut(BaseModel):
    id_inspeccion: uuid.UUID
    numero_inspeccion: int
    fecha_programada: date
    fecha_vencimiento: date | None
    origen: str
    id_tipo_inspeccion: int
    descripcion_tipo: str | None
    id_periodicidad: int | None
    ruta_id: uuid.UUID
    ruta_nombre: str
    finca: SincronizacionFincaOut
    ultimo_levantamiento: SincronizacionUltimoLevantamientoOut | None


class SincronizacionMapaFechaOut(BaseModel):
    """Una fecha con puntos en `fincas.pmtiles` (filtro por `fecha_programada` en la app)."""

    fecha: date
    total_puntos: int


class SincronizacionMapaOut(BaseModel):
    """Capa de fincas incluida en el ZIP (`fincas.pmtiles`), para dibujarla sobre el mapa base."""

    fincas_pmtiles: str
    capa: str
    total_puntos: int
    fechas: list[SincronizacionMapaFechaOut] = []
    # Capa de líneas de las rutas óptimas dentro del mismo archivo; None si no hay ninguna ruta.
    capa_rutas: str | None = None


class RutaOrigenOut(BaseModel):
    latitud: float
    longitud: float


class RutaParadaOut(BaseModel):
    orden: int
    latitud: float
    longitud: float
    # Varias inspecciones en el mismo punto son una sola parada.
    id_inspecciones: list[uuid.UUID]
    distancia_m_desde_anterior: int
    duracion_s_desde_anterior: int
    # Cuánto movió OSRM el punto para engancharlo a la calle más cercana.
    distancia_a_la_via_m: int


class RutaOptimaOut(BaseModel):
    """Ruta óptima de una fecha, desde el punto en que el inspector sincronizó."""

    fecha: date
    estado: Literal["ok", "sin_ruta"]
    # Solo con estado sin_ruta: origen_fuera_de_panama | osrm_no_disponible | sin_ruta_vial.
    motivo: str | None = None
    origen: RutaOrigenOut
    distancia_m: int | None = None
    duracion_s: int | None = None
    paradas: list[RutaParadaOut] = []


class SincronizacionMetaOut(BaseModel):
    email_inspector: str
    fecha_referencia: date
    fecha_generacion: datetime
    total_inspecciones: int
    # None cuando no se generó la capa (sin coordenadas o falla de tippecanoe).
    mapa: SincronizacionMapaOut | None = None


class SincronizacionResponse(BaseModel):
    meta: SincronizacionMetaOut
    catalogos: SincronizacionCatalogosOut
    # Vacío si la sincronización no envió origen o no hay OSRM configurado.
    rutas_optimas: list[RutaOptimaOut] = Field(default_factory=list)
    inspecciones: list[SincronizacionInspeccionOut]
