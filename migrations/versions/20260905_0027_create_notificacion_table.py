"""Create the notificacion table backing the inspections notification bell.

Revision ID: 20260905_0027
Revises: 20260905_0026
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0027"
down_revision: str | None = "20260905_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inspecciones.notificacion (
            id_notificacion     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email_destinatario  VARCHAR(255) NOT NULL,
            rol_origen          VARCHAR(50),
            tipo_notificacion   VARCHAR(50) NOT NULL,
            titulo              VARCHAR(255) NOT NULL,
            mensaje             VARCHAR(1000) NOT NULL,
            referencia_tipo     VARCHAR(50),
            referencia_id       UUID,
            estado              VARCHAR(20) NOT NULL DEFAULT 'NO_LEIDA'
                CHECK (estado IN ('NO_LEIDA', 'VISTA', 'SILENCIADA', 'CERRADA')),
            fecha_creacion      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fecha_vista         TIMESTAMPTZ,
            fecha_silenciada    TIMESTAMPTZ,
            fecha_cerrada       TIMESTAMPTZ,
            creado_por          VARCHAR(150)
        )
    """)
    op.execute("""
        CREATE INDEX idx_notificacion_destinatario_estado
            ON inspecciones.notificacion (email_destinatario, estado, fecha_creacion DESC)
    """)
    op.execute("""
        CREATE INDEX idx_notificacion_referencia_activa
            ON inspecciones.notificacion (referencia_tipo, referencia_id, tipo_notificacion)
            WHERE estado IN ('NO_LEIDA', 'VISTA')
    """)
    op.execute("""
        COMMENT ON TABLE inspecciones.notificacion IS
            'Bandeja de notificaciones por usuario para la campanita del módulo de inspecciones'
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inspecciones.notificacion")
