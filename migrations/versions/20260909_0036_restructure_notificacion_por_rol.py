"""Restructure notificacion for role-targeted rows and per-user read tracking.

Notifications targeted at a role used to be resolved against a Microsoft Entra ID
group at creation time, fanning out into one row per resolved email. This drops
that fan-out: a role notification is now a single row (notificacion.rol_destino),
resolved against each reader's role at query time instead of at creation time.
Per-user read/silence state moves out of notificacion.estado (which could only
belong to one email) into the new notificacion_lectura table, keyed by
(id_notificacion, email_lector); absence of a row there means unread.

notificacion.estado collapses from the old four values (NO_LEIDA/VISTA/SILENCIADA/
CERRADA) into notificacion.estado_notificacion (ACTIVA/CERRADA), which now
represents only the notification's own lifecycle (CERRADA = superseded by a newer
notification for the same reference, still done by close_previous), not who has
read it.

Revision ID: 20260909_0036
Revises: 20260908_0035
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260909_0036"
down_revision: str | None = "20260908_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ADD COLUMN rol_destino VARCHAR(50),
            ADD COLUMN estado_notificacion VARCHAR(20) NOT NULL DEFAULT 'ACTIVA'
                CHECK (estado_notificacion IN ('ACTIVA', 'CERRADA'))
    """)
    op.execute("""
        UPDATE inspecciones.notificacion
            SET estado_notificacion = 'CERRADA'
            WHERE estado = 'CERRADA'
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ALTER COLUMN email_destinatario DROP NOT NULL
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ADD CONSTRAINT chk_notificacion_destinatario_unico CHECK (
                (rol_destino IS NOT NULL AND email_destinatario IS NULL)
                OR
                (rol_destino IS NULL AND email_destinatario IS NOT NULL)
            )
    """)

    op.execute("""
        CREATE TABLE inspecciones.notificacion_lectura (
            id_notificacion  UUID NOT NULL
                REFERENCES inspecciones.notificacion(id_notificacion) ON DELETE CASCADE,
            email_lector     VARCHAR(255) NOT NULL,
            estado_lector    VARCHAR(20) NOT NULL DEFAULT 'VISTA'
                CHECK (estado_lector IN ('VISTA', 'SILENCIADA')),
            fecha_vista      TIMESTAMPTZ,
            fecha_silenciada TIMESTAMPTZ,
            PRIMARY KEY (id_notificacion, email_lector)
        )
    """)
    op.execute("""
        COMMENT ON TABLE inspecciones.notificacion_lectura IS
            'Estado de lectura por usuario de una notificacion; ausencia de fila = no leida'
    """)

    # Backfill: cada fila histórica ya tenía su lectura fijada a un único email_destinatario.
    op.execute("""
        INSERT INTO inspecciones.notificacion_lectura (
            id_notificacion, email_lector, estado_lector, fecha_vista, fecha_silenciada
        )
        SELECT id_notificacion, email_destinatario,
               CASE WHEN estado = 'SILENCIADA' THEN 'SILENCIADA' ELSE 'VISTA' END,
               fecha_vista,
               fecha_silenciada
        FROM inspecciones.notificacion
        WHERE estado IN ('VISTA', 'SILENCIADA')
    """)

    op.execute("DROP INDEX IF EXISTS inspecciones.idx_notificacion_destinatario_estado")
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_notificacion_referencia_activa")
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            DROP COLUMN rol_origen,
            DROP COLUMN estado,
            DROP COLUMN fecha_vista,
            DROP COLUMN fecha_silenciada
    """)

    op.execute("""
        CREATE INDEX idx_notificacion_rol_destino
            ON inspecciones.notificacion (rol_destino, fecha_creacion DESC)
            WHERE estado_notificacion = 'ACTIVA'
    """)
    op.execute("""
        CREATE INDEX idx_notificacion_email_destinatario
            ON inspecciones.notificacion (email_destinatario, fecha_creacion DESC)
            WHERE estado_notificacion = 'ACTIVA'
    """)
    op.execute("""
        CREATE INDEX idx_notificacion_referencia_activa
            ON inspecciones.notificacion (referencia_tipo, referencia_id, tipo_notificacion)
            WHERE estado_notificacion = 'ACTIVA'
    """)
    op.execute("""
        CREATE INDEX idx_notificacion_lectura_email
            ON inspecciones.notificacion_lectura (email_lector)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ADD COLUMN rol_origen VARCHAR(50),
            ADD COLUMN estado VARCHAR(20) NOT NULL DEFAULT 'NO_LEIDA'
                CHECK (estado IN ('NO_LEIDA', 'VISTA', 'SILENCIADA', 'CERRADA')),
            ADD COLUMN fecha_vista TIMESTAMPTZ,
            ADD COLUMN fecha_silenciada TIMESTAMPTZ
    """)
    op.execute("""
        UPDATE inspecciones.notificacion n
            SET estado = l.estado_lector,
                fecha_vista = l.fecha_vista,
                fecha_silenciada = l.fecha_silenciada
            FROM inspecciones.notificacion_lectura l
            WHERE l.id_notificacion = n.id_notificacion
              AND l.email_lector = n.email_destinatario
    """)
    op.execute("""
        UPDATE inspecciones.notificacion
            SET estado = 'CERRADA'
            WHERE estado_notificacion = 'CERRADA'
    """)
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_notificacion_lectura_email")
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_notificacion_referencia_activa")
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_notificacion_email_destinatario")
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_notificacion_rol_destino")
    op.execute("DROP TABLE IF EXISTS inspecciones.notificacion_lectura")

    op.execute("""
        ALTER TABLE inspecciones.notificacion
            DROP CONSTRAINT chk_notificacion_destinatario_unico
    """)
    # Las filas que solo tenían rol_destino (sin email) no pueden restaurar un
    # email_destinatario histórico: se eliminan, ya que el modelo anterior no las admitía.
    op.execute("DELETE FROM inspecciones.notificacion WHERE email_destinatario IS NULL")
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ALTER COLUMN email_destinatario SET NOT NULL,
            DROP COLUMN rol_destino,
            DROP COLUMN estado_notificacion
    """)

    op.execute("""
        CREATE INDEX idx_notificacion_destinatario_estado
            ON inspecciones.notificacion(email_destinatario, estado, fecha_creacion DESC)
    """)
    op.execute("""
        CREATE INDEX idx_notificacion_referencia_activa
            ON inspecciones.notificacion(referencia_tipo, referencia_id, tipo_notificacion)
            WHERE estado IN ('NO_LEIDA', 'VISTA')
    """)
