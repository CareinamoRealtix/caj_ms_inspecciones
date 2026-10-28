"""Guardar la clave S3 de fotos y firmas en lugar de la URL pública de CloudFront.

La API firma la URL al devolverla (ver docs/planes/PLAN_URLS_FIRMADAS_FOTOS.md). Esta migración
quita el prefijo `https://<dominio>.cloudfront.net/` de las filas existentes y deja solo
`fotos/...` o `firmas/...`. Solo toca URLs de CloudFront; cualquier otra URL queda igual.

Revision ID: 20261018_0059
Revises: 20261013_0058
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261018_0059"
down_revision: str | None = "20261013_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREFIJO = r"^https://[^/]+\.cloudfront\.net/((fotos|firmas)/.*)$"


def upgrade() -> None:
    op.execute(f"""
        UPDATE inspecciones.inspeccion_fotografia
        SET url_s3 = regexp_replace(url_s3, '{_PREFIJO}', '\\1')
        WHERE url_s3 ~ '{_PREFIJO}'
    """)
    op.execute(f"""
        UPDATE inspecciones.levantamiento_inspeccion
        SET url_firma_inspector = regexp_replace(url_firma_inspector, '{_PREFIJO}', '\\1')
        WHERE url_firma_inspector ~ '{_PREFIJO}'
    """)


def downgrade() -> None:
    # No reversible: el dominio de CloudFront depende del entorno. La API sigue leyendo ambos
    # formatos, así que no hace falta revertir los datos.
    pass
