"""Drop the legacy id_estado_inspeccion/es_activo columns and estado_inspeccion table.

Since 20260907_0029, activa + fecha_realizada are the sole source of
truth for an inspection's lifecycle; id_estado_inspeccion and es_activo
were kept only as unused legacy columns and no application code reads
or writes them anymore. This migration removes them along with the now
orphaned inspecciones.estado_inspeccion catalog table.

Dropping id_estado_inspeccion also drops (via cascade of the dropped
column) its FK to estado_inspeccion and the idx_inspeccion_estado index.
Dropping es_activo also drops idx_inspeccion_programada, which is
recreated here using activa instead so the "próximas programadas"
lookup keeps its index.

Revision ID: 20260907_0031
Revises: 20260907_0030
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260907_0031"
down_revision: str | None = "20260907_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP COLUMN IF EXISTS id_estado_inspeccion,
            DROP COLUMN IF EXISTS es_activo
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_programada
            ON inspecciones.inspeccion(fecha_programada)
            WHERE activa = TRUE
    """)
    op.execute("DROP TABLE IF EXISTS inspecciones.estado_inspeccion")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS inspecciones.estado_inspeccion (
            id_estado_inspeccion SERIAL PRIMARY KEY,
            nombre               VARCHAR(255) NOT NULL UNIQUE,
            descripcion          VARCHAR(255),
            color_badge          VARCHAR(20)
        )
    """)
    op.execute("""
        INSERT INTO inspecciones.estado_inspeccion (nombre, descripcion, color_badge)
        VALUES
            ('Activa',       'Inspección asignada al inspector',                   '#28a745'),
            ('En proceso',   'Adelantada por el inspector sin finalización',       '#ffc107'),
            ('Programada',   'Inspección periódica programada automáticamente',    '#17a2b8'),
            ('Inactiva',     'Inspección que fue reprogramada',                    '#6c757d'),
            ('Reprogramada', 'Modificada: fecha, inspector, tipo o periodicidad',  '#fd7e14'),
            ('Finalizada',   'Inspección realizada y cerrada',                     '#007bff')
        ON CONFLICT (nombre) DO NOTHING
    """)

    op.execute("""
        DROP INDEX IF EXISTS inspecciones.idx_inspeccion_programada
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN IF NOT EXISTS es_activo BOOLEAN NOT NULL DEFAULT TRUE
    """)
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET es_activo = activa
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN IF NOT EXISTS id_estado_inspeccion INTEGER
    """)
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET id_estado_inspeccion = (
            SELECT id_estado_inspeccion
            FROM inspecciones.estado_inspeccion
            WHERE nombre = CASE WHEN activa THEN 'Activa' ELSE 'Finalizada' END
        )
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN id_estado_inspeccion SET NOT NULL,
            ALTER COLUMN id_estado_inspeccion SET DEFAULT 1,
            ADD CONSTRAINT inspeccion_id_estado_inspeccion_fkey
                FOREIGN KEY (id_estado_inspeccion)
                REFERENCES inspecciones.estado_inspeccion(id_estado_inspeccion)
                ON DELETE RESTRICT
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_estado
            ON inspecciones.inspeccion(id_estado_inspeccion)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_programada
            ON inspecciones.inspeccion(fecha_programada)
            WHERE es_activo = TRUE
    """)
