"""Migrate notificacion.estado_notificacion to the estado_notificacion_enum domain.

El CHECK inline ya validaba estos mismos valores desde 20260909_0036, así que ninguna
fila existente puede violar el dominio; se elimina el CHECK de la columna porque el
dominio pasa a cubrirlo.

Revision ID: 20260922_0044
Revises: 20260922_0043
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0044"
down_revision: str | None = "20260922_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            DROP CONSTRAINT notificacion_estado_notificacion_check
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ALTER COLUMN estado_notificacion TYPE inspecciones.estado_notificacion_enum
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ALTER COLUMN estado_notificacion TYPE VARCHAR(20)
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ADD CONSTRAINT notificacion_estado_notificacion_check
                CHECK (estado_notificacion IN ('ACTIVA', 'CERRADA'))
    """)
