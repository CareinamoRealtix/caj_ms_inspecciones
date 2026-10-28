"""Drop the obsolete parent inspection relationship.

Revision ID: 20260829_0009
Revises: 20260827_0008
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0009"
down_revision: str | None = "20260827_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Cada inspección es independiente. La periodicidad solo determina su fecha
    # de vencimiento y no enlaza ni genera una inspección sucesora.
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP COLUMN IF EXISTS id_inspeccion_padre
    """)


def downgrade() -> None:
    # Los valores anteriores no pueden reconstruirse después de eliminar la
    # columna; un downgrade la restaura vacía y opcional.
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN id_inspeccion_padre UUID
                REFERENCES inspecciones.inspeccion(id_inspeccion) ON DELETE SET NULL
    """)
