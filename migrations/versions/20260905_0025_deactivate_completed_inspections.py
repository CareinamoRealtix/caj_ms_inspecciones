"""Deactivate completed inspections and enforce one active inspection per bien+finca.

Revision ID: 20260905_0025
Revises: 20260903_0024
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0025"
down_revision: str | None = "20260903_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET es_activo = FALSE
        WHERE fecha_realizada IS NOT NULL
          AND es_activo = TRUE
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_inspeccion_activa_por_bien_finca
            ON inspecciones.inspeccion (id_bien_inventario, numero_finca)
            WHERE es_activo = TRUE
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS inspecciones.ux_inspeccion_activa_por_bien_finca
    """)
