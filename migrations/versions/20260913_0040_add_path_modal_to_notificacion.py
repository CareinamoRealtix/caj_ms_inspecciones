"""Add path and modal columns to notificacion.

El frontend necesita saber a qué ruta navegar al hacer clic en una notificación
(path, opcional) y si debe abrirse en un modal en vez de navegar (modal, por
defecto false).

Revision ID: 20260913_0040
Revises: 20260913_0039
Create Date: 2026-09-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260913_0040"
down_revision: str | None = "20260913_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ADD COLUMN path VARCHAR(255),
            ADD COLUMN modal BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.notificacion.path IS
            'Ruta del frontend a la que navegar al hacer clic en la notificación'
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.notificacion.modal IS
            'Si la notificación debe abrirse en un modal en vez de navegar a path'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            DROP COLUMN path,
            DROP COLUMN modal
    """)
