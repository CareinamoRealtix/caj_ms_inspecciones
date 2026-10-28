"""Create the rol_notificacion_enum domain (Fase 2 del plan de dominios).

Refleja exactamente los valores de RolNotificacion en
app/presentation/api/schemas/notificaciones.py. Si se agrega un rol nuevo ahí, hace
falta una migración adicional (ALTER DOMAIN ... DROP CONSTRAINT + ADD CONSTRAINT)
para mantener ambos lados sincronizados.

Revision ID: 20260922_0047
Revises: 20260922_0046
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0047"
down_revision: str | None = "20260922_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE DOMAIN inspecciones.rol_notificacion_enum AS VARCHAR(50)
            CHECK (VALUE IN ('INSPECTOR', 'OFICIAL_BIENES_ADQUIRIDOS'))
    """)


def downgrade() -> None:
    op.execute("DROP DOMAIN IF EXISTS inspecciones.rol_notificacion_enum")
