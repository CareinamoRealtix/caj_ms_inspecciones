"""Create default routes for inventory assets.

Revision ID: 20260829_0011
Revises: 20260829_0010
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0011"
down_revision: str | None = "20260829_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inspecciones.bien_inventario_ruta (
            id_bien_inventario UUID PRIMARY KEY,
            id_ruta            VARCHAR(100) NOT NULL
                REFERENCES inspecciones.ruta(id) ON DELETE RESTRICT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inspecciones.bien_inventario_ruta")
