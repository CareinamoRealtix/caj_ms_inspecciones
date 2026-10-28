"""Create the canal_origen_enum domain (Fase 1 del plan de dominios).

Revision ID: 20260922_0045
Revises: 20260922_0044
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0045"
down_revision: str | None = "20260922_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE DOMAIN inspecciones.canal_origen_enum AS VARCHAR(10)
            CHECK (VALUE IN ('WEB', 'MOVIL'))
    """)


def downgrade() -> None:
    op.execute("DROP DOMAIN IF EXISTS inspecciones.canal_origen_enum")
