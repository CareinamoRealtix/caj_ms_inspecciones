"""Drop the obsolete automatic scheduling flag.

Revision ID: 20260829_0014
Revises: 20260829_0013
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0014"
down_revision: str | None = "20260829_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT IF EXISTS chk_inspeccion_periodicidad_vencimiento
    """)
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET fecha_vencimiento = NULL
        WHERE fecha_vencimiento IS NOT NULL
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP COLUMN IF EXISTS requiere_programacion_automatica
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.fecha_vencimiento IS
            'TODO: cálculo pendiente de definición; temporalmente siempre NULL'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN requiere_programacion_automatica BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD CONSTRAINT chk_inspeccion_periodicidad_vencimiento
            CHECK (
                requiere_programacion_automatica = FALSE
                AND fecha_vencimiento IS NULL
            )
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.fecha_vencimiento IS
            'Fecha de vencimiento calculada para la inspección'
    """)
