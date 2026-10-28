"""Remove the persisted periodicity relationship from inspections.

Revision ID: 20260829_0012
Revises: 20260829_0011
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0012"
down_revision: str | None = "20260829_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT IF EXISTS chk_inspeccion_periodicidad_vencimiento,
            DROP CONSTRAINT IF EXISTS inspeccion_id_periodicidad_fkey,
            DROP COLUMN IF EXISTS id_periodicidad
    """)

    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD CONSTRAINT chk_inspeccion_periodicidad_vencimiento
            CHECK (
                (
                    requiere_programacion_automatica = TRUE
                    AND fecha_vencimiento IS NOT NULL
                )
                OR (
                    requiere_programacion_automatica = FALSE
                    AND fecha_vencimiento IS NULL
                )
            )
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT IF EXISTS chk_inspeccion_periodicidad_vencimiento,
            ADD COLUMN id_periodicidad INTEGER
                REFERENCES inspecciones.periodicidad(id_periodicidad) ON DELETE RESTRICT
    """)

    # Recupera la periodicidad cuando la diferencia de fechas todavía coincide
    # con un valor vigente del catálogo.
    op.execute("""
        UPDATE inspecciones.inspeccion i
        SET id_periodicidad = p.id_periodicidad
        FROM inspecciones.periodicidad p
        WHERE i.requiere_programacion_automatica = TRUE
          AND i.fecha_vencimiento - i.fecha_programada = p.dias_vigencia
    """)

    # Una periodicidad que ya no existe en el catálogo no puede reconstruirse.
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET requiere_programacion_automatica = FALSE,
            fecha_vencimiento = NULL
        WHERE requiere_programacion_automatica = TRUE
          AND id_periodicidad IS NULL
    """)

    op.execute("""
        ALTER TABLE inspecciones.inspeccion
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
