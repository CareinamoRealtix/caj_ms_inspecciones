"""Add an independent fue_vista boolean to notificacion_lectura.

Until now, notificacion_lectura.estado_lector conflated two unrelated things into
one exclusive value: whether the reader had seen the notification (VISTA) and
whether they had muted it (SILENCIADA) — a reader could not have both states at
once. This adds notificacion_lectura.fue_vista as its own boolean, independent of
silenciado: marking a notification as "vista" now just flips this flag, and a
notification can be both seen and silenced.

estado_lector keeps tracking only the mute state going forward (its historical
'VISTA' values are migrated into fue_vista and cleared, and the column becomes
nullable — NULL means "not silenced"). EstadoNotificacion.VISTA is retired from
the API since "seen" is now expressed by NotificacionItem.fue_vista instead of
by a value of `estado`; NO_LEIDA and SILENCIADA remain for the ?estado= filter,
computed the same way as before (COALESCE(l.estado_lector, 'NO_LEIDA')).

Revision ID: 20260912_0037
Revises: 20260909_0036
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260912_0037"
down_revision: str | None = "20260909_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            ADD COLUMN fue_vista BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        UPDATE inspecciones.notificacion_lectura
            SET fue_vista = TRUE
            WHERE estado_lector = 'VISTA'
    """)
    # El NOT NULL y el CHECK de estado_lector deben caer antes de poner NULL en
    # filas reales con estado_lector = 'VISTA': si no, el UPDATE de abajo viola
    # el NOT NULL todavía vigente sobre esa columna.
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            DROP CONSTRAINT notificacion_lectura_estado_lector_check,
            ALTER COLUMN estado_lector DROP NOT NULL,
            ALTER COLUMN estado_lector DROP DEFAULT
    """)
    op.execute("""
        UPDATE inspecciones.notificacion_lectura
            SET estado_lector = NULL
            WHERE estado_lector = 'VISTA'
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            ADD CONSTRAINT chk_notificacion_lectura_estado_lector
                CHECK (estado_lector IS NULL OR estado_lector = 'SILENCIADA')
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.notificacion_lectura.fue_vista IS
            'Si el lector abrió/vio la notificación; independiente de si la silenció'
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.notificacion_lectura.estado_lector IS
            'NULL = no silenciada; SILENCIADA = el lector la ocultó de su lista activa'
    """)


def downgrade() -> None:
    # Best-effort: el modelo anterior solo admitía un valor exclusivo por lector
    # (VISTA o SILENCIADA), así que una fila que hoy es fue_vista=TRUE y también
    # SILENCIADA solo puede volver a representarse como SILENCIADA.
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            DROP CONSTRAINT chk_notificacion_lectura_estado_lector
    """)
    op.execute("""
        UPDATE inspecciones.notificacion_lectura
            SET estado_lector = 'VISTA'
            WHERE fue_vista = TRUE AND estado_lector IS NULL
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            ALTER COLUMN estado_lector SET DEFAULT 'VISTA',
            ALTER COLUMN estado_lector SET NOT NULL,
            ADD CONSTRAINT notificacion_lectura_estado_lector_check
                CHECK (estado_lector IN ('VISTA', 'SILENCIADA')),
            DROP COLUMN fue_vista
    """)
