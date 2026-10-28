"""Create the usuario_auditoria domain (Fase 5 del plan de dominios).

Mismo tipo/CHECK que el dominio email (Fase 3): creado_por/modificado_por siempre
guardan el email del usuario autenticado -- get_current_user_email (app/
presentation/api/dependencies/inspecciones.py) siempre devuelve un email o
responde 401, nunca un placeholder como "sistema".

Revision ID: 20260922_0053
Revises: 20260922_0052
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0053"
down_revision: str | None = "20260922_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(r"""
        CREATE DOMAIN inspecciones.usuario_auditoria AS VARCHAR(255)
            CHECK (VALUE ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$')
    """)


def downgrade() -> None:
    op.execute("DROP DOMAIN IF EXISTS inspecciones.usuario_auditoria")
