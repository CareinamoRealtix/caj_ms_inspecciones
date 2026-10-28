"""Valida los códigos de catálogo enviados en un levantamiento (HU 8)."""
from __future__ import annotations

import asyncpg

from app.presentation.api.schemas.inspecciones import LevantamientoRequest, SeleccionOpcion


class CodigoCatalogoInvalidoError(Exception):
    """Un código enviado no existe, está inactivo o no cumple las reglas de su grupo."""

    def __init__(self, tipo_catalogo: str, codigo: str, motivo: str) -> None:
        self.tipo_catalogo = tipo_catalogo
        self.codigo = codigo
        self.motivo = motivo
        super().__init__(f"Código inválido '{codigo}' en {tipo_catalogo}: {motivo}")


def agrupar_opciones(rows: list[asyncpg.Record]) -> dict[str, dict[str, asyncpg.Record]]:
    agrupado: dict[str, dict[str, asyncpg.Record]] = {}
    for row in rows:
        agrupado.setdefault(row["tipo_catalogo"], {})[row["codigo"]] = row
    return agrupado


def _validar_codigo_simple(
    tipo_catalogo: str, codigo: str, grupo: dict[str, asyncpg.Record]
) -> None:
    if codigo not in grupo:
        raise CodigoCatalogoInvalidoError(tipo_catalogo, codigo, "no existe o está inactivo")


def _validar_seleccion(
    tipo_catalogo: str, seleccion: SeleccionOpcion, grupo: dict[str, asyncpg.Record]
) -> None:
    opcion = grupo.get(seleccion.codigo)
    if opcion is None:
        raise CodigoCatalogoInvalidoError(
            tipo_catalogo, seleccion.codigo, "no existe o está inactivo"
        )
    if opcion["requiere_cantidad"] and seleccion.cantidad is None:
        raise CodigoCatalogoInvalidoError(tipo_catalogo, seleccion.codigo, "requiere cantidad")
    if opcion["permite_descripcion"] and not seleccion.descripcion:
        raise CodigoCatalogoInvalidoError(tipo_catalogo, seleccion.codigo, "requiere descripción")
    if not opcion["permite_descripcion"] and seleccion.descripcion:
        raise CodigoCatalogoInvalidoError(tipo_catalogo, seleccion.codigo, "no permite descripción")


def _validar_lista(
    tipo_catalogo: str,
    seleccion: list[SeleccionOpcion] | None,
    opciones: dict[str, dict[str, asyncpg.Record]],
) -> None:
    if not seleccion:
        return
    grupo = opciones.get(tipo_catalogo, {})
    for item in seleccion:
        _validar_seleccion(tipo_catalogo, item, grupo)


def validar_codigos(
    body: LevantamientoRequest, opciones: dict[str, dict[str, asyncpg.Record]]
) -> None:
    _validar_codigo_simple(
        "CONDICION_BIEN", body.condicion_bien, opciones.get("CONDICION_BIEN", {})
    )
    _validar_codigo_simple(
        "ESTADO_OCUPACION", body.estado_ocupacion, opciones.get("ESTADO_OCUPACION", {})
    )
    if body.tipo_identificacion_ocup is not None:
        _validar_codigo_simple(
            "TIPO_IDENTIFICACION_OCUPANTE",
            body.tipo_identificacion_ocup,
            opciones.get("TIPO_IDENTIFICACION_OCUPANTE", {}),
        )

    if body.puertas:
        ubicaciones = opciones.get("UBICACION_PUERTA", {})
        materiales = opciones.get("PUERTA_MATERIAL", {})
        for ubicacion, selecciones in body.puertas.items():
            _validar_codigo_simple("UBICACION_PUERTA", ubicacion, ubicaciones)
            for seleccion in selecciones:
                _validar_seleccion("PUERTA_MATERIAL", seleccion, materiales)

    _validar_lista("VENTANA_TIPO", body.tipos_ventanas, opciones)
    _validar_lista("SERVICIO_PUBLICO", body.servicios_publicos, opciones)
    _validar_lista("DISTRIBUCION_INMUEBLE", body.distribucion_inmueble, opciones)
    _validar_lista("INSPECCION_TECNICA", body.tipos_inspeccion_tecnica, opciones)

    for tipo_servicio, selecciones in (body.servicios_requeridos or {}).items():
        _validar_lista(tipo_servicio, selecciones, opciones)
