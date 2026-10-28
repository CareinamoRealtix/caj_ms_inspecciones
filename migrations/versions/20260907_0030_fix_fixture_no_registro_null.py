"""Fix the v_consulta_inventario fixture row: no_registro must not be NULL.

Migration 20260907_0028 left no_registro as NULL on the synthetic
"Christian" fixture row. bien_inventario.no_registro is a plain
NOT NULL integer (not a domain), so this didn't break CREATE OR REPLACE
VIEW, but GestionItemResponse.no_registro is a required int field.
Since this fixture bien has no inspection tied to it, it is included by
/gestion and /control when nuevo_ingreso=true, and building the response
for it raised a pydantic ValidationError (HTTP 500) because no_registro
came back as None. This migration recreates the view with a real
placeholder (0) instead of NULL.

Revision ID: 20260907_0030
Revises: 20260907_0029
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260907_0030"
down_revision: str | None = "20260907_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FIXTURE_ID_BIEN_INVENTARIO = "1e4f4400-9091-5b61-8ccb-488c38311339"

_BASE_VIEW_SQL = """
    SELECT
        bi.id_bien_inventario,
        bi.id_bien,
        bi.no_registro,
        fincas.numero_finca,
        fincas.numeros_finca,
        d.nombre_deudor,
        d.numero_prestamo,
        bi.id_tipo_propiedad,
        tp.descripcion AS tipo_propiedad,
        prov.id_provincia,
        prov.nombre AS provincia,
        dist.id_distrito,
        b.fecha_inscripcion,
        b.monto_adjudicado,
        ic.valor_avaluo,
        bi.id_estatus_bien,
        ebi.nombre AS estatus_bien,
        ebi.color_badge,
        bi.id_estado_inventario,
        ei.nombre AS estado_inventario,
        bi.id_oficinista,
        ofi.nombre AS oficinista,
        bi.usuario_registrador,
        bi.fecha_recibido_inventario,
        bi.fecha_ingreso_inventario,
        bi.es_activo,
        cor.id_corregimiento,
        dist.nombre AS distrito,
        cor.nombre AS corregimiento,
        dir.barrio AS barriada_sector,
        dir.direccion,
        dir.numero_lote,
        dir.url_ubicacion_geoespacial,
        ST_Y(ST_PointOnSurface(dir.geom_direccion)) AS latitud,
        ST_X(ST_PointOnSurface(dir.geom_direccion)) AS longitud,
        bi.fecha_creacion
    FROM bien.bien_inventario bi
    LEFT JOIN bien.bien b
        ON b.id_bien = bi.id_bien
    LEFT JOIN bien.deudor d
        ON d.id_deudor = b.id_deudor
    LEFT JOIN bien.tipo_propiedad tp
        ON tp.id_tipo_propiedad = bi.id_tipo_propiedad
    LEFT JOIN bien.direccion dir
        ON dir.id_direccion = b.id_direccion
    LEFT JOIN bien.corregimiento cor
        ON cor.id_corregimiento = dir.id_corregimiento
    LEFT JOIN bien.distrito dist
        ON dist.id_distrito = cor.id_distrito
    LEFT JOIN bien.provincia prov
        ON prov.id_provincia = dist.id_provincia
    LEFT JOIN bien.informacion_contable ic
        ON ic.id_bien_inventario = bi.id_bien_inventario
    LEFT JOIN bien.estatus_bien_inventario ebi
        ON ebi.id_estatus_bien_inventario = bi.id_estatus_bien
    LEFT JOIN bien.estado_inventario ei
        ON ei.id_estado_inventario = bi.id_estado_inventario
    LEFT JOIN bien.oficinista ofi
        ON ofi.id_oficinista = bi.id_oficinista
    LEFT JOIN LATERAL (
        SELECT
            STRING_AGG(
                f.numero_finca::text,
                '-' ORDER BY f.numero_finca::text
            ) AS numero_finca,
            COALESCE(
                ARRAY_AGG(
                    f.numero_finca::text
                    ORDER BY f.numero_finca::text
                ) FILTER (WHERE f.numero_finca IS NOT NULL),
                ARRAY[]::text[]
            ) AS numeros_finca
        FROM bien.finca f
        WHERE f.id_bien = b.id_bien
    ) fincas ON true
"""

_FIXTURE_ROW_SQL_BROKEN = f"""
    SELECT
        '{_FIXTURE_ID_BIEN_INVENTARIO}'::bien.dom_id_transaccional AS id_bien_inventario,
        NULL::bien.dom_fk_uuid_opt AS id_bien,
        NULL AS no_registro,
        '1111' AS numero_finca,
        ARRAY['1111'] AS numeros_finca,
        'CHRISTIAN (REGISTRO DE PRUEBA)'::bien.dom_texto_corto_opt AS nombre_deudor,
        NULL::bien.dom_numero_prestamo_opt AS numero_prestamo,
        NULL::bien.dom_fk_int_opt AS id_tipo_propiedad,
        'N/A (fixture)'::bien.dom_texto_corto_req AS tipo_propiedad,
        NULL::integer AS id_provincia,
        'N/A (fixture)'::bien.dom_texto_obligatorio AS provincia,
        NULL::integer AS id_distrito,
        NULL::bien.dom_fecha_opt AS fecha_inscripcion,
        NULL::bien.dom_monto_adjudicado_opt AS monto_adjudicado,
        0::bien.dom_monto_financiero_req AS valor_avaluo,
        NULL::bien.dom_fk_int_opt AS id_estatus_bien,
        'N/A (fixture)'::bien.dom_texto_corto_req AS estatus_bien,
        NULL::character varying(7) AS color_badge,
        0::bien.dom_fk_int AS id_estado_inventario,
        'Registro de prueba'::bien.dom_texto_corto_req AS estado_inventario,
        NULL::bien.dom_fk_int_opt AS id_oficinista,
        'N/A (fixture)'::bien.dom_texto_obligatorio AS oficinista,
        'fixture-christian@sistema.local'::bien.dom_correo_electronico_opt AS usuario_registrador,
        NULL::bien.dom_fecha_opt AS fecha_recibido_inventario,
        CURRENT_DATE::bien.dom_fecha_default AS fecha_ingreso_inventario,
        TRUE::bien.dom_boolean_default_true AS es_activo,
        NULL::integer AS id_corregimiento,
        'N/A (fixture)'::bien.dom_texto_obligatorio AS distrito,
        'N/A (fixture)'::bien.dom_texto_obligatorio AS corregimiento,
        NULL::bien.dom_texto_corto_opt AS barriada_sector,
        'Registro sintetico de prueba (fixture local)'::bien.dom_texto_corto_opt AS direccion,
        NULL::bien.dom_texto_corto_opt AS numero_lote,
        NULL::character varying(255) AS url_ubicacion_geoespacial,
        NULL::double precision AS latitud,
        NULL::double precision AS longitud,
        now()::bien.dom_timestamp_default AS fecha_creacion
"""

_FIXTURE_ROW_SQL_FIXED = _FIXTURE_ROW_SQL_BROKEN.replace(
    "NULL AS no_registro,", "0 AS no_registro,"
)


def upgrade() -> None:
    op.execute(
        "CREATE OR REPLACE VIEW inspecciones.v_consulta_inventario AS"
        + _BASE_VIEW_SQL
        + "UNION ALL"
        + _FIXTURE_ROW_SQL_FIXED
    )


def downgrade() -> None:
    op.execute(
        "CREATE OR REPLACE VIEW inspecciones.v_consulta_inventario AS"
        + _BASE_VIEW_SQL
        + "UNION ALL"
        + _FIXTURE_ROW_SQL_BROKEN
    )
