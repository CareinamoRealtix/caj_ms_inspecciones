"""Create a view over bien.bien_inventario.

Revision ID: 20260826_0003
Revises: 20260825_0002
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260826_0003"
down_revision: str | None = "20260825_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW inspecciones.vw_bien_inventario AS
        SELECT *
        FROM bien.bien_inventario
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS inspecciones.vw_bien_inventario")
