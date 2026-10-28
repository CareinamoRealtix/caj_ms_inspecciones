"""Generación del informe PDF de inspección (Gerencia de Bienes Adquiridos).

Replica el diseño de la plantilla institucional: encabezado con logo, franja de
identificación, datos del bien, detalles del inmueble, puertas/ventanas,
distribución, servicios requeridos, observaciones y registro fotográfico.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.presentation.api.schemas.inspecciones import (
    DetalleInspeccionResponse,
    FotografiaDetail,
    LevantamientoDetail,
    LevantamientoOpcionOut,
    SeleccionOpcion,
)

_LOGO_PATH = Path(__file__).parent / "assets" / "logo_caja_ahorros.png"

_AZUL = colors.HexColor("#1B4F8C")
_AZUL_TEXTO = colors.HexColor("#0B4C8C")
_GRIS_FONDO = colors.HexColor("#EEEEEE")
_GRIS_BORDE = colors.HexColor("#BFBFBF")
_GRIS_TEXTO = colors.HexColor("#595959")

_ANCHO_UTIL = A4[0] - 3 * cm

_TITULO_STYLE = ParagraphStyle(
    "TituloInforme",
    fontName="Helvetica-Bold",
    fontSize=16,
    textColor=_AZUL_TEXTO,
    alignment=TA_CENTER,
    leading=19,
)
_SUBTITULO_STYLE = ParagraphStyle(
    "SubtituloInforme",
    fontName="Helvetica",
    fontSize=10,
    textColor=_GRIS_TEXTO,
    alignment=TA_CENTER,
)
_SECCION_STYLE = ParagraphStyle(
    "SeccionTitulo",
    fontName="Helvetica-Bold",
    fontSize=10,
    textColor=_AZUL_TEXTO,
    alignment=TA_CENTER,
)
_CAMPO_STYLE = ParagraphStyle(
    "Campo",
    fontName="Helvetica",
    fontSize=9,
    leading=12,
)
_CELDA_STYLE = ParagraphStyle(
    "Celda",
    fontName="Helvetica",
    fontSize=8.5,
    leading=11,
)
_CELDA_HEADER_STYLE = ParagraphStyle(
    "CeldaHeader",
    fontName="Helvetica-Bold",
    fontSize=8.5,
    leading=11,
    textColor=_AZUL_TEXTO,
)
_OBSERVACIONES_STYLE = ParagraphStyle(
    "Observaciones",
    fontName="Helvetica",
    fontSize=9,
    leading=13,
)
_CAPTION_STYLE = ParagraphStyle(
    "Caption",
    fontName="Helvetica",
    fontSize=8,
    alignment=TA_CENTER,
    textColor=_GRIS_TEXTO,
)
_FIRMA_STYLE = ParagraphStyle(
    "Firma",
    fontName="Helvetica-Bold",
    fontSize=9,
    alignment=TA_CENTER,
)


def _campo(label: str, value: str | None) -> Paragraph:
    texto = escape(value) if value else "—"
    return Paragraph(f"<b>{escape(label)}:</b> {texto}", _CAMPO_STYLE)


def _fecha(value: object) -> str | None:
    if value is None:
        return None
    return value.strftime("%d/%m/%Y")  # type: ignore[union-attr]


def _numero_identificacion(numero_inspeccion: int) -> str:
    return f"INSP-{numero_inspeccion:03d}"


class _Catalogo:
    """Índice codigo->opción por tipo_catalogo, para traducir códigos a nombres."""

    def __init__(self, catalogos: dict[str, list[LevantamientoOpcionOut]]) -> None:
        self._catalogos = catalogos
        self._por_codigo: dict[str, dict[str, LevantamientoOpcionOut]] = {
            tipo: {op.codigo: op for op in opciones} for tipo, opciones in catalogos.items()
        }

    def opciones_ordenadas(self, tipo_catalogo: str) -> list[LevantamientoOpcionOut]:
        return sorted(self._catalogos.get(tipo_catalogo, []), key=lambda o: o.orden)

    def nombre(self, tipo_catalogo: str, codigo: str) -> str:
        opcion = self._por_codigo.get(tipo_catalogo, {}).get(codigo)
        return opcion.nombre if opcion else codigo

    def contiene(self, tipo_catalogo: str, codigo: str) -> bool:
        return codigo in self._por_codigo.get(tipo_catalogo, {})


def _formatear_seleccion(seleccion: SeleccionOpcion, nombre: str) -> str:
    texto = nombre
    if seleccion.cantidad:
        texto = f"{texto} ({seleccion.cantidad})"
    if seleccion.descripcion:
        texto = f"{texto} - {seleccion.descripcion}"
    return texto


def _seccion_header(titulo: str) -> Table:
    tabla = Table([[Paragraph(titulo.upper(), _SECCION_STYLE)]], colWidths=[_ANCHO_UTIL])
    tabla.setStyle(
        TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 1, _AZUL),
            ("LINEABOVE", (0, 0), (-1, -1), 1, _AZUL),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    return tabla


def _bloque_campos(
    filas: list[list[Paragraph]],
    *,
    fondo: colors.Color | None = None,
) -> Table:
    n_cols = max(len(fila) for fila in filas)
    ancho_col = _ANCHO_UTIL / n_cols
    tabla = Table(filas, colWidths=[ancho_col] * n_cols)
    estilo = [
        ("BOX", (0, 0), (-1, -1), 0.75, _GRIS_BORDE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if fondo is not None:
        estilo.append(("BACKGROUND", (0, 0), (-1, -1), fondo))
    tabla.setStyle(TableStyle(estilo))
    return tabla


def _tabla_puertas(lev: LevantamientoDetail, catalogo: _Catalogo) -> Table:
    ubicaciones = catalogo.opciones_ordenadas("UBICACION_PUERTA") or [
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
    ]
    puertas = lev.puertas or {}

    filas = [
        [Paragraph("Material", _CELDA_HEADER_STYLE)]
        + [Paragraph(u.nombre, _CELDA_HEADER_STYLE) for u in ubicaciones]
    ]
    for material in catalogo.opciones_ordenadas("PUERTA_MATERIAL"):
        fila = [Paragraph(material.nombre, _CELDA_STYLE)]
        for ubicacion in ubicaciones:
            seleccion = next(
                (
                    s
                    for s in puertas.get(ubicacion.codigo, [])
                    if s.codigo == material.codigo
                ),
                None,
            )
            valor = str(seleccion.cantidad or 1) if seleccion else "-"
            fila.append(Paragraph(valor, _CELDA_STYLE))
        filas.append(fila)

    ancho_material = 3.2 * cm
    ancho_valor = (_ANCHO_UTIL / 2 - ancho_material) / len(ubicaciones)
    tabla = Table(filas, colWidths=[ancho_material] + [ancho_valor] * len(ubicaciones))
    tabla.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, _GRIS_BORDE),
            ("BACKGROUND", (0, 0), (-1, 0), _GRIS_FONDO),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )
    return tabla


def _tabla_ventanas(lev: LevantamientoDetail, catalogo: _Catalogo) -> Table:
    seleccionadas = {s.codigo: s for s in (lev.tipos_ventanas or [])}
    filas = [
        [
            Paragraph("Tipo de Ventana", _CELDA_HEADER_STYLE),
            Paragraph("Cant.", _CELDA_HEADER_STYLE),
        ]
    ]
    for tipo in catalogo.opciones_ordenadas("VENTANA_TIPO"):
        seleccion = seleccionadas.get(tipo.codigo)
        valor = str(seleccion.cantidad or 1) if seleccion else "-"
        filas.append([Paragraph(tipo.nombre, _CELDA_STYLE), Paragraph(valor, _CELDA_STYLE)])

    ancho_valor = 1.8 * cm
    ancho_nombre = _ANCHO_UTIL / 2 - ancho_valor
    tabla = Table(filas, colWidths=[ancho_nombre, ancho_valor])
    tabla.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, _GRIS_BORDE),
            ("BACKGROUND", (0, 0), (-1, 0), _GRIS_FONDO),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )
    return tabla


def _tabla_distribucion(lev: LevantamientoDetail, catalogo: _Catalogo) -> Table | None:
    seleccionadas = {s.codigo: s for s in (lev.distribucion_inmueble or [])}
    if not seleccionadas:
        return None

    celdas = [
        Paragraph(
            f"<b>{escape(item.nombre)}:</b> {seleccionadas[item.codigo].cantidad or 1}",
            _CAMPO_STYLE,
        )
        for item in catalogo.opciones_ordenadas("DISTRIBUCION_INMUEBLE")
        if item.codigo in seleccionadas
    ]
    n_cols = 4
    filas = [celdas[i : i + n_cols] for i in range(0, len(celdas), n_cols)]
    ultima = filas[-1]
    if len(ultima) < n_cols:
        ultima.extend([Paragraph("", _CAMPO_STYLE)] * (n_cols - len(ultima)))

    return _bloque_campos(filas)


def _servicios_requeridos(lev: LevantamientoDetail, catalogo: _Catalogo) -> list[Paragraph]:
    seleccion = lev.servicios_requeridos or {}

    def _items_de(tipo_catalogo: str) -> list[str]:
        return [
            _formatear_seleccion(s, catalogo.nombre(tipo_catalogo, s.codigo))
            for s in seleccion.get(tipo_catalogo, [])
        ]

    grupos: list[tuple[str, list[str]]] = [
        ("Limpieza", _items_de("LIMPIEZA")),
        ("Cerrajería", _items_de("CERRAJERIA_MATERIAL")),
        ("Reparación", _items_de("REPARACION")),
    ]
    if lev.inspeccion_tecnica_req:
        tipos = [
            catalogo.nombre("INSPECCION_TECNICA", s.codigo)
            for s in (lev.tipos_inspeccion_tecnica or [])
        ]
        grupos.append(("Inspección Técnica", tipos))

    parrafos = [
        Paragraph(
            f"<b>{escape(nombre)}:</b> Requerido - {escape(' / '.join(items)) if items else '—'}",
            _OBSERVACIONES_STYLE,
        )
        for nombre, items in grupos
        if items or nombre == "Inspección Técnica"
    ]
    if not parrafos:
        parrafos = [Paragraph("Sin servicios requeridos registrados.", _OBSERVACIONES_STYLE)]
    return parrafos


def _foto_celda(
    foto: FotografiaDetail,
    contenido: bytes | None,
    *,
    ancho: float,
    alto: float,
) -> Table:
    fondo_placeholder = None
    if contenido:
        imagen = Image(io.BytesIO(contenido), width=ancho, height=alto, kind="proportional")
        imagen.hAlign = "CENTER"
        cuerpo = imagen
    else:
        cuerpo = Paragraph("Imagen no disponible", _CAPTION_STYLE)
        fondo_placeholder = _GRIS_FONDO

    etiqueta = foto.nombre_archivo or "Fotografía"
    tabla = Table(
        [[cuerpo], [Paragraph(escape(etiqueta), _CAPTION_STYLE)]],
        colWidths=[ancho],
        rowHeights=[alto, None],
    )
    estilo = [
        ("BOX", (0, 0), (-1, -1), 0.5, _GRIS_BORDE),
        ("LINEBELOW", (0, 0), (0, 0), 0.5, _GRIS_BORDE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]
    if fondo_placeholder is not None:
        estilo.append(("BACKGROUND", (0, 0), (0, 0), fondo_placeholder))
    tabla.setStyle(TableStyle(estilo))
    return tabla


def _grid_fotografias(
    fotografias: list[FotografiaDetail],
    fotos_bytes: dict[uuid.UUID, bytes | None],
) -> Table:
    n_cols = 3
    ancho_celda = _ANCHO_UTIL / n_cols
    alto_imagen = 4 * cm

    celdas = [
        _foto_celda(
            foto,
            fotos_bytes.get(foto.id_fotografia),
            ancho=ancho_celda - 0.4 * cm,
            alto=alto_imagen,
        )
        for foto in fotografias
    ]
    filas = [celdas[i : i + n_cols] for i in range(0, len(celdas), n_cols)]
    ultima = filas[-1]
    if len(ultima) < n_cols:
        ultima.extend([Paragraph("", _CAPTION_STYLE)] * (n_cols - len(ultima)))

    tabla = Table(filas, colWidths=[ancho_celda] * n_cols)
    tabla.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    return tabla


def _encabezado() -> list[object]:
    elementos: list[object] = []
    if _LOGO_PATH.is_file():
        logo = Image(str(_LOGO_PATH), width=5 * cm, height=1.8 * cm, kind="proportional")
        logo.hAlign = "LEFT"
        elementos.append(logo)
        elementos.append(Spacer(1, 0.2 * cm))
    elementos.append(Paragraph("INFORME DE INSPECCIÓN", _TITULO_STYLE))
    elementos.append(Paragraph("Gerencia de Bienes Adquiridos", _SUBTITULO_STYLE))
    elementos.append(Spacer(1, 0.3 * cm))
    return elementos


def generar_pdf_inspeccion(
    detalle: DetalleInspeccionResponse,
    catalogos: dict[str, list[LevantamientoOpcionOut]],
    *,
    inspector_nombre: str,
    fotos_bytes: dict[uuid.UUID, bytes | None] | None = None,
    firma_bytes: bytes | None = None,
) -> bytes:
    catalogo = _Catalogo(catalogos)
    fotos_bytes = fotos_bytes or {}
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    elementos: list[object] = []
    elementos.extend(_encabezado())

    elementos.append(
        _bloque_campos([
            [
                _campo(
                    "No. de Identificación de Inspección",
                    _numero_identificacion(detalle.numero_inspeccion),
                ),
                _campo("Fecha", _fecha(detalle.fecha_realizada or detalle.fecha_programada)),
            ],
            [
                _campo("Inspector", inspector_nombre),
                _campo("Tipo", detalle.tipo_inspeccion),
            ],
        ])
    )
    elementos.append(Spacer(1, 0.3 * cm))

    elementos.append(_seccion_header("Datos del Bien"))
    elementos.append(
        _bloque_campos([
            [
                _campo("No. de Finca", detalle.numero_finca),
                _campo("Provincia", detalle.provincia),
                _campo("Distrito", detalle.distrito),
                _campo("Corregimiento", detalle.corregimiento),
            ],
            [
                _campo("Barriada/Sector/PH", detalle.barriada_sector),
                _campo(
                    "Calle/No. de Casa",
                    " / ".join(
                        parte
                        for parte in [detalle.direccion, detalle.numero_lote]
                        if parte
                    )
                    or None,
                ),
            ],
        ])
    )
    elementos.append(Spacer(1, 0.3 * cm))

    lev = detalle.levantamiento
    if lev is not None:
        elementos.append(_seccion_header("Detalles del Inmueble"))
        elementos.append(
            _bloque_campos(
                [
                    [
                        _campo(
                            "Estado de Ocupación",
                            catalogo.nombre("ESTADO_OCUPACION", lev.estado_ocupacion),
                        ),
                        _campo(
                            "Condición del bien",
                            catalogo.nombre("CONDICION_BIEN", lev.condicion_bien),
                        ),
                    ],
                    [
                        _campo("Nombre del Ocupante", lev.ocupante.nombre),
                        _campo("Cédula", lev.ocupante.numero_identificacion),
                    ],
                ],
                fondo=_GRIS_FONDO,
            )
        )
        elementos.append(Spacer(1, 0.3 * cm))

        tabla_puertas = _tabla_puertas(lev, catalogo)
        tabla_ventanas = _tabla_ventanas(lev, catalogo)
        titulos = [
            Paragraph("<b>Puertas</b>", _CELDA_HEADER_STYLE),
            Paragraph("<b>Tipo de Ventanas</b>", _CELDA_HEADER_STYLE),
        ]
        tabla_lado_a_lado = Table(
            [titulos, [tabla_puertas, tabla_ventanas]],
            colWidths=[_ANCHO_UTIL / 2, _ANCHO_UTIL / 2],
        )
        tabla_lado_a_lado.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ])
        )
        elementos.append(tabla_lado_a_lado)
        elementos.append(Spacer(1, 0.3 * cm))

        nombres_servicios = [
            catalogo.nombre("SERVICIO_PUBLICO", s.codigo) for s in (lev.servicios_publicos or [])
        ]
        elementos.append(
            _campo("Servicios Públicos", " / ".join(nombres_servicios) or None)
        )
        elementos.append(Spacer(1, 0.3 * cm))

        tabla_distribucion = _tabla_distribucion(lev, catalogo)
        if tabla_distribucion is not None:
            elementos.append(_seccion_header("Distribución"))
            elementos.append(tabla_distribucion)
            elementos.append(Spacer(1, 0.3 * cm))

        elementos.append(_seccion_header("Servicios Requeridos"))
        elementos.extend(_servicios_requeridos(lev, catalogo))
        elementos.append(Spacer(1, 0.3 * cm))

        elementos.append(_seccion_header("Observaciones"))
        elementos.append(Spacer(1, 0.15 * cm))
        elementos.append(
            Paragraph(escape(lev.observaciones) if lev.observaciones else "—", _OBSERVACIONES_STYLE)
        )
    else:
        elementos.append(
            Paragraph(
                "El levantamiento de campo aún no ha sido registrado para esta inspección.",
                _OBSERVACIONES_STYLE,
            )
        )

    if detalle.fotografias:
        elementos.append(PageBreak())
        elementos.extend(_encabezado())
        elementos.append(_seccion_header("Registro Fotográfico"))
        elementos.append(Spacer(1, 0.3 * cm))
        elementos.append(_grid_fotografias(detalle.fotografias, fotos_bytes))

    elementos.append(Spacer(1, 1.2 * cm))
    if firma_bytes:
        firma_img = Image(io.BytesIO(firma_bytes), width=4 * cm, height=2 * cm, kind="proportional")
        firma_img.hAlign = "CENTER"
        elementos.append(firma_img)
    else:
        elementos.append(Paragraph("(espacio para firma digital)", _CAPTION_STYLE))
    elementos.append(Spacer(1, 0.6 * cm))
    linea_firma = Table([[""]], colWidths=[7 * cm])
    linea_firma.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 0.75, colors.black)]))
    linea_firma.hAlign = "CENTER"
    elementos.append(linea_firma)
    elementos.append(Spacer(1, 0.15 * cm))
    elementos.append(Paragraph(escape(inspector_nombre), _FIRMA_STYLE))

    doc.build(elementos)
    return buffer.getvalue()
