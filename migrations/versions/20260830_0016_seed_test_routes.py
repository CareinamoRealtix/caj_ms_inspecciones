"""Seed test routes for local and development environments.

Revision ID: 20260830_0016
Revises: 20260830_0015
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0016"
down_revision: str | None = "20260830_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO inspecciones.ruta (id, nombre)
        VALUES
            ('RUTA-001', 'Ruta Centro'),
            ('RUTA-002', 'Ruta Este'),
            ('RUTA-003', 'Ruta Oeste')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM inspecciones.ruta
        WHERE (id, nombre) IN (
            ('RUTA-001', 'Ruta Centro'),
            ('RUTA-002', 'Ruta Este'),
            ('RUTA-003', 'Ruta Oeste')
        )
    """)
