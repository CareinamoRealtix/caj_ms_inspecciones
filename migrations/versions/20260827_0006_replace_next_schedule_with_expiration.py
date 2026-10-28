"""Replace next scheduling date with inspection expiration date.

Revision ID: 20260827_0006
Revises: 20260827_0005
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260827_0006"
down_revision: str | None = "20260827_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.periodicidad
            RENAME COLUMN dias_habiles TO dias_vigencia
    """)

    op.execute("""
        UPDATE inspecciones.periodicidad
        SET dias_vigencia = CASE nombre
            WHEN 'Diaria' THEN 1
            WHEN 'Semanal' THEN 7
            WHEN 'Quincenal' THEN 15
            WHEN 'Mensual' THEN 30
            WHEN 'Bimensual' THEN 60
            WHEN 'Trimestral' THEN 90
            WHEN 'Semestral' THEN 180
            WHEN 'Anual' THEN 365
            ELSE dias_vigencia
        END
    """)
    op.execute("""
        UPDATE inspecciones.estado_inspeccion
        SET descripcion = 'Inspección programada para una fecha futura'
        WHERE nombre = 'Programada'
    """)

    op.execute("DROP INDEX IF EXISTS inspecciones.idx_inspeccion_periodica")
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN fecha_vencimiento DATE
    """)

    op.execute("""
        UPDATE inspecciones.inspeccion i
        SET fecha_vencimiento = i.fecha_programada + p.dias_vigencia
        FROM inspecciones.periodicidad p
        WHERE p.id_periodicidad = i.id_periodicidad
          AND i.requiere_programacion_automatica = TRUE
    """)

    op.execute("""
        UPDATE inspecciones.inspeccion
        SET requiere_programacion_automatica = FALSE,
            id_periodicidad = NULL,
            fecha_vencimiento = NULL
        WHERE requiere_programacion_automatica = FALSE
           OR id_periodicidad IS NULL
    """)

    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP COLUMN fecha_siguiente_programacion,
            ADD CONSTRAINT chk_inspeccion_periodicidad_vencimiento
            CHECK (
                (
                    requiere_programacion_automatica = TRUE
                    AND id_periodicidad IS NOT NULL
                    AND fecha_vencimiento IS NOT NULL
                )
                OR (
                    requiere_programacion_automatica = FALSE
                    AND id_periodicidad IS NULL
                    AND fecha_vencimiento IS NULL
                )
            )
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE inspecciones.estado_inspeccion
        SET descripcion = 'Inspección periódica programada automáticamente'
        WHERE nombre = 'Programada'
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT IF EXISTS chk_inspeccion_periodicidad_vencimiento,
            ADD COLUMN fecha_siguiente_programacion DATE
    """)
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET fecha_siguiente_programacion = fecha_vencimiento
        WHERE requiere_programacion_automatica = TRUE
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP COLUMN fecha_vencimiento
    """)

    op.execute("""
        UPDATE inspecciones.periodicidad
        SET dias_vigencia = CASE nombre
            WHEN 'Diaria' THEN 1
            WHEN 'Semanal' THEN 5
            WHEN 'Quincenal' THEN 10
            WHEN 'Mensual' THEN 22
            WHEN 'Bimensual' THEN 44
            WHEN 'Trimestral' THEN 65
            WHEN 'Semestral' THEN 130
            WHEN 'Anual' THEN 261
            ELSE dias_vigencia
        END
    """)
    op.execute("""
        ALTER TABLE inspecciones.periodicidad
            RENAME COLUMN dias_vigencia TO dias_habiles
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_periodica
            ON inspecciones.inspeccion(
                requiere_programacion_automatica,
                fecha_siguiente_programacion
            )
            WHERE requiere_programacion_automatica = TRUE AND es_activo = TRUE
    """)
