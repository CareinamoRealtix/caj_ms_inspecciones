"""Seed additional test routes.

Revision ID: 20260831_0018
Revises: 20260831_0017
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0018"
down_revision: str | None = "20260831_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO inspecciones.ruta (id, nombre)
        VALUES
            ('RUTA-004', 'Ruta Norte'),
            ('RUTA-005', 'Ruta Sur'),
            ('RUTA-006', 'Ruta Metropolitana')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM inspecciones.ruta
        WHERE (id, nombre) IN (
            ('RUTA-004', 'Ruta Norte'),
            ('RUTA-005', 'Ruta Sur'),
            ('RUTA-006', 'Ruta Metropolitana')
        )
    """)
