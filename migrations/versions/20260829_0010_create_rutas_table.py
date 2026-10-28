"""Create the routes catalog table.

Revision ID: 20260829_0010
Revises: 20260829_0009
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0010"
down_revision: str | None = "20260829_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inspecciones.ruta (
            id     VARCHAR(100) PRIMARY KEY,
            nombre VARCHAR(255) NOT NULL UNIQUE,
            CONSTRAINT chk_ruta_valores_no_vacios
                CHECK (BTRIM(id) <> '' AND BTRIM(nombre) <> '')
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inspecciones.ruta")
