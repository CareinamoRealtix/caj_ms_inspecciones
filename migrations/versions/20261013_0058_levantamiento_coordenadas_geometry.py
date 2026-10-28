"""Store levantamiento coordinates as a PostGIS point instead of a "lat,lng" string.

Replaces inspecciones.levantamiento_inspeccion.coordenadas (VARCHAR) with
geom_levantamiento geometry(Point, 4326), the same SRID used by bien.direccion.geom_direccion
(X = longitude, Y = latitude). Existing rows are converted; values that are not a valid
"lat,lng" pair become NULL.

Revision ID: 20261013_0058
Revises: 20260929_0057
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261013_0058"
down_revision: str | None = "20260929_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAR_VALIDO = r"^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.levantamiento_inspeccion
            ADD COLUMN geom_levantamiento geometry(Point, 4326)
    """)
    op.execute(f"""
        UPDATE inspecciones.levantamiento_inspeccion
        SET geom_levantamiento = ST_SetSRID(ST_MakePoint(
                trim(split_part(coordenadas, ',', 2))::float8,
                trim(split_part(coordenadas, ',', 1))::float8), 4326)
        WHERE coordenadas ~ '{_PAR_VALIDO}'
          AND abs(trim(split_part(coordenadas, ',', 1))::float8) <= 90
          AND abs(trim(split_part(coordenadas, ',', 2))::float8) <= 180
    """)
    op.execute("ALTER TABLE inspecciones.levantamiento_inspeccion DROP COLUMN coordenadas")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.levantamiento_inspeccion
            ADD COLUMN coordenadas VARCHAR(100)
    """)
    op.execute("""
        UPDATE inspecciones.levantamiento_inspeccion
        SET coordenadas = ST_Y(geom_levantamiento)::text || ',' || ST_X(geom_levantamiento)::text
        WHERE geom_levantamiento IS NOT NULL
    """)
    op.execute("ALTER TABLE inspecciones.levantamiento_inspeccion DROP COLUMN geom_levantamiento")
