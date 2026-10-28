"""Migrate inspeccion.origen to the canal_origen_enum domain.

El CHECK inline ya validaba estos mismos valores desde 20260825_0002, así que ninguna
fila existente puede violar el dominio; se elimina el CHECK de la columna porque el
dominio pasa a cubrirlo.

Revision ID: 20260922_0046
Revises: 20260922_0045
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0046"
down_revision: str | None = "20260922_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT inspeccion_origen_check
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN origen TYPE inspecciones.canal_origen_enum
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN origen TYPE VARCHAR(10)
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD CONSTRAINT inspeccion_origen_check
                CHECK (origen IN ('WEB', 'MOVIL'))
    """)
