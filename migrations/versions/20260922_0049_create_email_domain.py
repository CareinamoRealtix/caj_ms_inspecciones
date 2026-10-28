"""Create the email domain (Fase 3 del plan de dominios).

VARCHAR(255): la mayor de las longitudes usadas hoy para columnas de email
(email_destinatario, email_lector); email_inspector se amplía de 150 a 255 al
migrarla para unificar el límite en las tres.

Revision ID: 20260922_0049
Revises: 20260922_0048
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0049"
down_revision: str | None = "20260922_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(r"""
        CREATE DOMAIN inspecciones.email AS VARCHAR(255)
            CHECK (VALUE ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$')
    """)


def downgrade() -> None:
    op.execute("DROP DOMAIN IF EXISTS inspecciones.email")
