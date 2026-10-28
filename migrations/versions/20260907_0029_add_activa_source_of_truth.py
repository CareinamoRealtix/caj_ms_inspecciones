"""Add activa as the inspection lifecycle source of truth.

Revision ID: 20260907_0029
Revises: 20260907_0028
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260907_0029"
down_revision: str | None = "20260907_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN activa BOOLEAN
    """)
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET activa = (fecha_realizada IS NULL)
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN activa SET DEFAULT TRUE,
            ALTER COLUMN activa SET NOT NULL,
            ALTER COLUMN id_estado_inspeccion SET DEFAULT 1
    """)

    op.execute("""
        DROP INDEX IF EXISTS inspecciones.ux_inspeccion_activa_por_bien_finca
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_inspeccion_activa_por_bien_finca
            ON inspecciones.inspeccion (id_bien_inventario, numero_finca)
            WHERE activa = TRUE
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD CONSTRAINT ck_inspeccion_activa_fecha_realizada
            CHECK (
                (activa = TRUE AND fecha_realizada IS NULL)
                OR
                (activa = FALSE AND fecha_realizada IS NOT NULL)
            )
    """)

    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.activa IS
            'Fuente de verdad del ciclo: TRUE pendiente; FALSE realizada'
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.es_activo IS
            'LEGACY: no usar para determinar si una inspeccion esta activa'
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.id_estado_inspeccion IS
            'LEGACY: no usar para determinar el ciclo de vida de la inspeccion'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT IF EXISTS ck_inspeccion_activa_fecha_realizada
    """)
    op.execute("""
        DROP INDEX IF EXISTS inspecciones.ux_inspeccion_activa_por_bien_finca
    """)
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET es_activo = activa,
            id_estado_inspeccion = CASE
                WHEN activa THEN (
                    SELECT id_estado_inspeccion
                    FROM inspecciones.estado_inspeccion
                    WHERE nombre = 'Activa'
                )
                ELSE (
                    SELECT id_estado_inspeccion
                    FROM inspecciones.estado_inspeccion
                    WHERE nombre = 'Finalizada'
                )
            END
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_inspeccion_activa_por_bien_finca
            ON inspecciones.inspeccion (id_bien_inventario, numero_finca)
            WHERE es_activo = TRUE
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN id_estado_inspeccion DROP DEFAULT,
            DROP COLUMN activa
    """)
