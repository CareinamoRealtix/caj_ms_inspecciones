"""Create the service-owned schema.

Revision ID: 20260823_0001
Revises:
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260823_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # En ejecución online, env.py crea el schema únicamente si aún no existe. La
    # condición explícita evita requerir CREATE sobre la base cuando un DBA ya lo
    # provisionó para el servicio.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_namespace WHERE nspname = 'inspecciones'
            ) THEN
                CREATE SCHEMA inspecciones;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    # El schema contiene la tabla de versión de Alembic y se conserva para que
    # el propio downgrade pueda registrarse de forma segura.
    pass
