"""Migrate notificacion.rol_destino to the rol_notificacion_enum domain.

rol_destino solo se validaba hasta ahora en Python (RolNotificacion); la base de
datos no rechazaba un INSERT directo con cualquier string. Antes de aplicar el
dominio se verifica que no existan filas con un valor que quedaría fuera del CHECK
(el dominio no evalúa NULL, así que el XOR con email_destinatario sigue intacto).

Revision ID: 20260922_0048
Revises: 20260922_0047
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0048"
down_revision: str | None = "20260922_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            invalidos INT;
        BEGIN
            SELECT COUNT(*) INTO invalidos
            FROM inspecciones.notificacion
            WHERE rol_destino IS NOT NULL
              AND rol_destino NOT IN ('INSPECTOR', 'OFICIAL_BIENES_ADQUIRIDOS');
            IF invalidos > 0 THEN
                RAISE EXCEPTION
                    'notificacion.rol_destino tiene % fila(s) fuera de RolNotificacion',
                    invalidos;
            END IF;
        END $$
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ALTER COLUMN rol_destino TYPE inspecciones.rol_notificacion_enum
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ALTER COLUMN rol_destino TYPE VARCHAR(50)
    """)
