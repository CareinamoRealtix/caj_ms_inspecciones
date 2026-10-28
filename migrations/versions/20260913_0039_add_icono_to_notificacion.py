"""Add icono column to notificacion.

El frontend necesita un ícono asociado a cada notificación. Por ahora todas las
notificaciones se crean con el mismo ícono ('info'); cuando existan tipos de
notificación con íconos distintos, este valor se podrá parametrizar en la
creación.

Revision ID: 20260913_0039
Revises: 20260912_0038
Create Date: 2026-09-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260913_0039"
down_revision: str | None = "20260912_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ADD COLUMN icono VARCHAR(50) NOT NULL DEFAULT 'info'
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.notificacion.icono IS
            'Ícono a mostrar en el frontend junto a la notificación'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            DROP COLUMN icono
    """)
