"""Corregir la opción VENTANA_TIPO 'Vidrios flojos' a 'Vidrios fijos'.

La HU 8 se sembró con 'Vidrios flojos' (VIDRIOS_FLOJOS) por error; el tipo de ventana correcto
es 'Vidrios fijos'. Se renombra el código y el nombre en levantamiento_opcion y se recodifican
las selecciones ya guardadas en levantamiento_inspeccion.tipos_ventanas, que guardan el código.

Revision ID: 20261027_0060
Revises: 20261018_0059
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261027_0060"
down_revision: str | None = "20261018_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _recodificar(codigo_anterior: str, codigo_nuevo: str, nombre_nuevo: str) -> None:
    op.execute(f"""
        UPDATE inspecciones.levantamiento_opcion
        SET codigo = '{codigo_nuevo}',
            nombre = '{nombre_nuevo}',
            fecha_modificacion = NOW()
        WHERE tipo_catalogo = 'VENTANA_TIPO'
          AND codigo = '{codigo_anterior}'
    """)
    op.execute(f"""
        UPDATE inspecciones.levantamiento_inspeccion l
        SET tipos_ventanas = (
            SELECT jsonb_agg(
                       CASE WHEN e.item ->> 'codigo' = '{codigo_anterior}'
                            THEN jsonb_set(e.item, '{{codigo}}', '"{codigo_nuevo}"')
                            ELSE e.item
                       END
                       ORDER BY e.ord)
            FROM jsonb_array_elements(l.tipos_ventanas) WITH ORDINALITY AS e(item, ord)
        )
        WHERE jsonb_typeof(l.tipos_ventanas) = 'array'
          AND l.tipos_ventanas @> '[{{"codigo": "{codigo_anterior}"}}]'
    """)


def upgrade() -> None:
    _recodificar("VIDRIOS_FLOJOS", "VIDRIOS_FIJOS", "Vidrios fijos")


def downgrade() -> None:
    _recodificar("VIDRIOS_FIJOS", "VIDRIOS_FLOJOS", "Vidrios flojos")
