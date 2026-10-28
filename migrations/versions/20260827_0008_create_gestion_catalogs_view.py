"""Create the read contract for management filter catalogs.

Revision ID: 20260827_0008
Revises: 20260827_0007
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260827_0008"
down_revision: str | None = "20260827_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW inspecciones.v_catalogos_gestion AS
        SELECT
            'ESTADO_OCUPACION'::text AS tipo_catalogo,
            eo.id_estatus_ocupacion::integer AS id,
            NULL::integer AS id_padre,
            eo.nombre::text AS nombre
        FROM bien.estatus_ocupacion eo

        UNION ALL

        SELECT
            'PROVINCIA'::text AS tipo_catalogo,
            p.id_provincia::integer AS id,
            NULL::integer AS id_padre,
            p.nombre::text AS nombre
        FROM bien.provincia p

        UNION ALL

        SELECT
            'DISTRITO'::text AS tipo_catalogo,
            d.id_distrito::integer AS id,
            d.id_provincia::integer AS id_padre,
            d.nombre::text AS nombre
        FROM bien.distrito d

        UNION ALL

        SELECT
            'CORREGIMIENTO'::text AS tipo_catalogo,
            c.id_corregimiento::integer AS id,
            c.id_distrito::integer AS id_padre,
            c.nombre::text AS nombre
        FROM bien.corregimiento c
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS inspecciones.v_catalogos_gestion")
