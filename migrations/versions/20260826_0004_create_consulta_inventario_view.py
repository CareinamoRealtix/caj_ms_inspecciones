"""Replace the initial inventory view with the consolidated read contract.

Revision ID: 20260826_0004
Revises: 20260826_0003
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260826_0004"
down_revision: str | None = "20260826_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS inspecciones.vw_bien_inventario")
    op.execute("""
        CREATE OR REPLACE VIEW inspecciones.v_consulta_inventario AS
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
            bi.es_activo
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
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS inspecciones.v_consulta_inventario")
    op.execute("""
        CREATE OR REPLACE VIEW inspecciones.vw_bien_inventario AS
        SELECT *
        FROM bien.bien_inventario
    """)
