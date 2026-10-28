from __future__ import annotations

import uuid
from datetime import date

from app.presentation.api.schemas.inspecciones import (
    DetalleInspeccionResponse,
    FotografiaDetail,
    LevantamientoDetail,
    LevantamientoOpcionOut,
    OcupanteDetail,
    SeleccionOpcion,
)
from app.presentation.pdf.inspeccion_pdf import generar_pdf_inspeccion

_CATALOGOS: dict[str, list[LevantamientoOpcionOut]] = {
    "UBICACION_PUERTA": [
        LevantamientoOpcionOut(
            codigo="ENTRADA_PRINCIPAL",
            nombre="Puerta Principal",
            requiere_cantidad=False,
            permite_descripcion=False,
            orden=1,
        ),
        LevantamientoOpcionOut(
            codigo="TRASERAS",
            nombre="Traseras",
            requiere_cantidad=False,
            permite_descripcion=False,
            orden=2,
        ),
    ],
    "PUERTA_MATERIAL": [
        LevantamientoOpcionOut(
            codigo="HIERRO",
            nombre="Hierro",
            requiere_cantidad=True,
            permite_descripcion=False,
            orden=1,
        ),
    ],
    "VENTANA_TIPO": [
        LevantamientoOpcionOut(
            codigo="FRANCESA",
            nombre="Francesa",
            requiere_cantidad=True,
            permite_descripcion=False,
            orden=1,
        ),
    ],
    "SERVICIO_PUBLICO": [
        LevantamientoOpcionOut(
            codigo="LUZ_CONECTADA",
            nombre="Luz eléctrica conectada",
            requiere_cantidad=False,
            permite_descripcion=False,
            orden=1,
        ),
    ],
    "DISTRIBUCION_INMUEBLE": [
        LevantamientoOpcionOut(
            codigo="SALA",
            nombre="Sala",
            requiere_cantidad=True,
            permite_descripcion=False,
            orden=1,
        ),
    ],
    "LIMPIEZA": [
        LevantamientoOpcionOut(
            codigo="INTERNA",
            nombre="Interna",
            requiere_cantidad=False,
            permite_descripcion=False,
            orden=1,
        ),
    ],
    "CERRAJERIA_MATERIAL": [],
    "REPARACION": [],
    "INSPECCION_TECNICA": [],
    "ESTADO_OCUPACION": [
        LevantamientoOpcionOut(
            codigo="OCUPADO",
            nombre="Ocupado",
            requiere_cantidad=False,
            permite_descripcion=False,
            orden=1,
        ),
    ],
    "CONDICION_BIEN": [
        LevantamientoOpcionOut(
            codigo="BUENA",
            nombre="Buena",
            requiere_cantidad=False,
            permite_descripcion=False,
            orden=1,
        ),
    ],
}


def _detalle(**overrides: object) -> DetalleInspeccionResponse:
    base = dict(
        id_inspeccion=uuid.uuid4(),
        numero_inspeccion=1,
        numero_finca="304826291",
        id_bien_inventario=uuid.uuid4(),
        ruta_id=uuid.uuid4(),
        ruta_nombre="Ruta 1",
        fecha_programada=date(2026, 8, 2),
        fecha_realizada=date(2026, 8, 2),
        tipo_inspeccion="Inspección de Rutina",
        descripcion_tipo=None,
        email_inspector="francisco.delarosa@example.com",
        estado_inspeccion="Finalizada",
        color_badge="#007bff",
        origen="programada",
        provincia="Panamá",
        distrito="Panamá",
        corregimiento="Pacora",
        barriada_sector="Residencial Mirador del Bosque",
        direccion="Calle Principal",
        numero_lote="Casa 215",
        levantamiento=None,
        fotografias=[],
    )
    base.update(overrides)
    return DetalleInspeccionResponse(**base)  # type: ignore[arg-type]


def test_generar_pdf_sin_levantamiento_no_falla() -> None:
    pdf_bytes = generar_pdf_inspeccion(
        _detalle(),
        _CATALOGOS,
        inspector_nombre="Francisco De La Rosa",
    )

    assert pdf_bytes.startswith(b"%PDF")


def test_generar_pdf_con_levantamiento_y_fotografias_agrega_segunda_pagina() -> None:
    lev = LevantamientoDetail(
        coordenadas=None,
        condicion_bien="BUENA",
        estado_ocupacion="OCUPADO",
        ocupante=OcupanteDetail(
            nombre="Alfredo Herrera Gutierrez",
            tipo_identificacion="CEDULA",
            numero_identificacion="8-507-1284",
            numero_contacto=None,
            comentarios=None,
        ),
        puertas={"ENTRADA_PRINCIPAL": [SeleccionOpcion(codigo="HIERRO", cantidad=1)]},
        tipos_ventanas=[SeleccionOpcion(codigo="FRANCESA", cantidad=4)],
        servicios_publicos=[SeleccionOpcion(codigo="LUZ_CONECTADA")],
        distribucion_inmueble=[SeleccionOpcion(codigo="SALA", cantidad=1)],
        servicios_requeridos={"LIMPIEZA": [SeleccionOpcion(codigo="INTERNA")]},
        inspeccion_tecnica_req=False,
        tipos_inspeccion_tecnica=None,
        motivacion=None,
        url_firma_inspector=None,
        observaciones="Inmueble en buen estado.",
        fecha_levantamiento=date(2026, 8, 2),
    )
    detalle_sin_fotos = _detalle(levantamiento=lev, fotografias=[])
    detalle_con_fotos = _detalle(
        levantamiento=lev,
        fotografias=[
            FotografiaDetail(
                id_fotografia=uuid.uuid4(),
                url_s3="https://example.com/1.jpg",
                nombre_archivo="Fachada principal",
                es_visible_geovisor=True,
                es_foto_principal=True,
                orden=1,
            )
        ],
    )

    pdf_sin_fotos = generar_pdf_inspeccion(
        detalle_sin_fotos, _CATALOGOS, inspector_nombre="Francisco De La Rosa"
    )
    pdf_con_fotos = generar_pdf_inspeccion(
        detalle_con_fotos, _CATALOGOS, inspector_nombre="Francisco De La Rosa"
    )

    assert pdf_sin_fotos.startswith(b"%PDF")
    assert pdf_con_fotos.startswith(b"%PDF")
    assert len(pdf_con_fotos) > len(pdf_sin_fotos)
