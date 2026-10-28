"""Group levantamiento_inspeccion.servicios_requeridos by tipo_servicio.

servicios_requeridos was a flat JSONB array mixing LIMPIEZA, CERRAJERIA_MATERIAL and
REPARACION selections; the service type was not stored and had to be looked up by code in
inspecciones.servicio. It becomes an object keyed by tipo_servicio, like puertas:

    [{"codigo": "INTERNA"}, {"codigo": "HIERRO", "cantidad": 2}]
    -> {"LIMPIEZA": [{"codigo": "INTERNA"}], "CERRAJERIA_MATERIAL": [{"codigo": "HIERRO", ...}]}

Rows whose codes cannot be matched to the catalog abort the migration instead of being
silently dropped. Only array-typed values are touched, so re-running is a no-op.

Revision ID: 20260929_0056
Revises: 20260922_0055
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260929_0056"
down_revision: str | None = "20260922_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE huerfanos TEXT;
        BEGIN
            SELECT string_agg(
                DISTINCT l.id_levantamiento::text || ':' || (e.item ->> 'codigo'), ', '
            )
            INTO huerfanos
            FROM inspecciones.levantamiento_inspeccion l
            CROSS JOIN LATERAL jsonb_array_elements(l.servicios_requeridos) AS e(item)
            LEFT JOIN inspecciones.servicio s
                   ON s.codigo = e.item ->> 'codigo'
                  AND s.tipo_servicio IN ('LIMPIEZA', 'CERRAJERIA_MATERIAL', 'REPARACION')
            WHERE jsonb_typeof(l.servicios_requeridos) = 'array'
              AND s.id_servicio IS NULL;

            IF huerfanos IS NOT NULL THEN
                RAISE EXCEPTION
                    'servicios_requeridos con códigos sin match en inspecciones.servicio: %',
                    huerfanos;
            END IF;
        END $$
    """)

    op.execute("""
        UPDATE inspecciones.levantamiento_inspeccion l
        SET servicios_requeridos = COALESCE((
            SELECT jsonb_object_agg(g.tipo_servicio, g.items)
            FROM (
                SELECT s.tipo_servicio,
                       jsonb_agg(e.item ORDER BY e.ord) AS items
                FROM jsonb_array_elements(l.servicios_requeridos)
                     WITH ORDINALITY AS e(item, ord)
                JOIN inspecciones.servicio s
                  ON s.codigo = e.item ->> 'codigo'
                 AND s.tipo_servicio IN ('LIMPIEZA', 'CERRAJERIA_MATERIAL', 'REPARACION')
                GROUP BY s.tipo_servicio
            ) g
        ), '{}'::jsonb)
        WHERE jsonb_typeof(l.servicios_requeridos) = 'array'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE inspecciones.levantamiento_inspeccion l
        SET servicios_requeridos = COALESCE((
            SELECT jsonb_agg(item ORDER BY
                       CASE g.key
                           WHEN 'LIMPIEZA' THEN 1
                           WHEN 'CERRAJERIA_MATERIAL' THEN 2
                           ELSE 3
                       END,
                       e.ord)
            FROM jsonb_each(l.servicios_requeridos) AS g(key, value)
            CROSS JOIN LATERAL jsonb_array_elements(g.value)
                 WITH ORDINALITY AS e(item, ord)
        ), '[]'::jsonb)
        WHERE jsonb_typeof(l.servicios_requeridos) = 'object'
    """)
