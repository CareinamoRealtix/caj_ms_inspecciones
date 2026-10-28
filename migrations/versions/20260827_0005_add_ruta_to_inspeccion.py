"""Add route data to inspections.

Revision ID: 20260827_0005
Revises: 20260826_0004
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260827_0005"
down_revision: str | None = "20260826_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN IF NOT EXISTS ruta_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS ruta_nombre VARCHAR(255)
    """)

    # Los registros anteriores a esta migración no tenían información de ruta.
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET ruta_id = COALESCE(ruta_id, 'SIN_RUTA'),
            ruta_nombre = COALESCE(ruta_nombre, 'Sin ruta asignada')
        WHERE ruta_id IS NULL OR ruta_nombre IS NULL
    """)

    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN ruta_id SET NOT NULL,
            ALTER COLUMN ruta_nombre SET NOT NULL
    """)

    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD CONSTRAINT chk_inspeccion_ruta_no_vacia
            CHECK (BTRIM(ruta_id) <> '' AND BTRIM(ruta_nombre) <> '')
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_ruta
            ON inspecciones.inspeccion(ruta_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_inspeccion_ruta")
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT IF EXISTS chk_inspeccion_ruta_no_vacia,
            DROP COLUMN IF EXISTS ruta_nombre,
            DROP COLUMN IF EXISTS ruta_id
    """)
