"""Replace notificacion_lectura.estado_lector with a plain fue_silenciada boolean.

estado_lector only ever held NULL or 'SILENCIADA' since fue_vista took over the
"seen" state (migration 20260912_0037). A string column with a single possible
non-null value is just a boolean with extra steps, and the alertas-vencimiento
job needs to filter and upsert this state directly (silence a stale "próxima a
vencer" alert once its inspection is overdue), so this makes it a real boolean:
notificacion_lectura.fue_silenciada, independent of fue_vista as before.

Revision ID: 20260912_0038
Revises: 20260912_0037
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260912_0038"
down_revision: str | None = "20260912_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            ADD COLUMN fue_silenciada BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        UPDATE inspecciones.notificacion_lectura
            SET fue_silenciada = TRUE
            WHERE estado_lector = 'SILENCIADA'
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            DROP CONSTRAINT chk_notificacion_lectura_estado_lector,
            DROP COLUMN estado_lector
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.notificacion_lectura.fue_silenciada IS
            'Si el lector ocultó la notificación de su lista activa; independiente de fue_vista'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            ADD COLUMN estado_lector VARCHAR(20)
    """)
    op.execute("""
        UPDATE inspecciones.notificacion_lectura
            SET estado_lector = 'SILENCIADA'
            WHERE fue_silenciada = TRUE
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            ADD CONSTRAINT chk_notificacion_lectura_estado_lector
                CHECK (estado_lector IS NULL OR estado_lector = 'SILENCIADA'),
            DROP COLUMN fue_silenciada
    """)
