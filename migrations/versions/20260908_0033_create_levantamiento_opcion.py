"""Create the levantamiento_opcion catalog table and seed HU 8 options.

Replaces the arbitrary JSONB content previously accepted by the levantamiento
endpoint with a locally-owned catalog of selectable codes per group
(tipo_catalogo), following the HU 8 field structure (puertas, ventanas,
servicios, distribucion del inmueble, servicios requeridos, inspeccion
tecnica) plus the scalar CONDICION_BIEN/ESTADO_OCUPACION/TIPO_IDENTIFICACION
options and a new UBICACION_PUERTA group (Entrada Principal / Traseras).

Revision ID: 20260908_0033
Revises: 20260907_0032
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0033"
down_revision: str | None = "20260907_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inspecciones.levantamiento_opcion (
            id_opcion             BIGSERIAL PRIMARY KEY,
            tipo_catalogo         VARCHAR(50) NOT NULL,
            codigo                VARCHAR(50) NOT NULL,
            nombre                VARCHAR(150) NOT NULL,
            requiere_cantidad     BOOLEAN NOT NULL DEFAULT FALSE,
            permite_descripcion   BOOLEAN NOT NULL DEFAULT FALSE,
            orden                 INTEGER NOT NULL DEFAULT 0,
            es_activo             BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_creacion        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fecha_modificacion    TIMESTAMPTZ,
            CONSTRAINT uq_levantamiento_opcion_tipo_codigo UNIQUE (tipo_catalogo, codigo)
        )
    """)

    op.execute("""
        CREATE INDEX idx_levantamiento_opcion_tipo
            ON inspecciones.levantamiento_opcion(tipo_catalogo, orden, nombre)
    """)

    op.execute("""
        COMMENT ON TABLE inspecciones.levantamiento_opcion IS
            'Catálogo de opciones del formulario de levantamiento (HU 8), agrupadas por grupo'
    """)

    op.execute("""
        INSERT INTO inspecciones.levantamiento_opcion
            (tipo_catalogo, codigo, nombre, requiere_cantidad, permite_descripcion, orden)
        VALUES
            ('CONDICION_BIEN', 'BUENA', 'Buena', FALSE, FALSE, 1),
            ('CONDICION_BIEN', 'REGULAR', 'Regular', FALSE, FALSE, 2),
            ('CONDICION_BIEN', 'VANDALIZADA', 'Vandalizada', FALSE, FALSE, 3),

            ('ESTADO_OCUPACION', 'DESOCUPADO', 'Desocupado', FALSE, FALSE, 1),
            ('ESTADO_OCUPACION', 'OCUPADO', 'Ocupado', FALSE, FALSE, 2),
            ('ESTADO_OCUPACION', 'INVADIDO', 'Invadido', FALSE, FALSE, 3),

            ('TIPO_IDENTIFICACION_OCUPANTE', 'CEDULA', 'Cédula de identidad', FALSE, FALSE, 1),
            ('TIPO_IDENTIFICACION_OCUPANTE', 'PASAPORTE', 'Pasaporte', FALSE, FALSE, 2),

            ('UBICACION_PUERTA', 'ENTRADA_PRINCIPAL', 'Entrada Principal', FALSE, FALSE, 1),
            ('UBICACION_PUERTA', 'TRASERAS', 'Traseras', FALSE, FALSE, 2),

            ('PUERTA_MATERIAL', 'HIERRO', 'Hierro', TRUE, FALSE, 1),
            ('PUERTA_MATERIAL', 'MULTILOCK', 'Multilock', TRUE, FALSE, 2),
            ('PUERTA_MATERIAL', 'MADERA', 'Madera', TRUE, FALSE, 3),
            ('PUERTA_MATERIAL', 'VIDRIO_ALUMINIO', 'Vidrio/Aluminio', TRUE, FALSE, 4),

            ('VENTANA_TIPO', 'VIDRIOS_FLOJOS', 'Vidrios flojos', TRUE, FALSE, 1),
            ('VENTANA_TIPO', 'ORNAMENTALES', 'Ornamentales', TRUE, FALSE, 2),
            ('VENTANA_TIPO', 'VERJAS', 'Verjas', TRUE, FALSE, 3),
            ('VENTANA_TIPO', 'PERSIANAS', 'Persianas', TRUE, FALSE, 4),
            ('VENTANA_TIPO', 'FRANCESA', 'Francesa', TRUE, FALSE, 5),
            ('VENTANA_TIPO', 'OTROS', 'Otros', TRUE, TRUE, 6),

            ('SERVICIO_PUBLICO', 'LUZ_CONECTADA', 'Luz eléctrica conectada', FALSE, FALSE, 1),
            ('SERVICIO_PUBLICO', 'AGUA_MEDIDOR', 'Con suministro de agua (medidor)',
             FALSE, FALSE, 2),
            ('SERVICIO_PUBLICO', 'AGUA_NIPLE', 'Con suministro de agua (niple)', FALSE, FALSE, 3),
            ('SERVICIO_PUBLICO', 'AGUA_DESCONECTADA', 'Servicio de agua desconectado',
             FALSE, FALSE, 4),

            ('DISTRIBUCION_INMUEBLE', 'SALA', 'Sala', TRUE, FALSE, 1),
            ('DISTRIBUCION_INMUEBLE', 'RECAMARA', 'Recámara', TRUE, FALSE, 2),
            ('DISTRIBUCION_INMUEBLE', 'COMEDOR', 'Comedor', TRUE, FALSE, 3),
            ('DISTRIBUCION_INMUEBLE', 'COCINA', 'Cocina', TRUE, FALSE, 4),
            ('DISTRIBUCION_INMUEBLE', 'BANOS', 'Baños', TRUE, FALSE, 5),
            ('DISTRIBUCION_INMUEBLE', 'DEPOSITO', 'Depósito', TRUE, FALSE, 6),
            ('DISTRIBUCION_INMUEBLE', 'PORTAL', 'Portal', TRUE, FALSE, 7),
            ('DISTRIBUCION_INMUEBLE', 'TERRAZA', 'Terraza', TRUE, FALSE, 8),
            ('DISTRIBUCION_INMUEBLE', 'LAVANDERIA', 'Lavandería', TRUE, FALSE, 9),
            ('DISTRIBUCION_INMUEBLE', 'PISCINA', 'Piscina', TRUE, FALSE, 10),

            ('LIMPIEZA', 'INTERNA', 'Interna', FALSE, FALSE, 1),
            ('LIMPIEZA', 'EXTERNA', 'Externa', FALSE, FALSE, 2),
            ('LIMPIEZA', 'RETIRO_ENSERES', 'Retiro de enseres', FALSE, FALSE, 3),
            ('LIMPIEZA', 'LIMPIEZA_PISCINA', 'Limpieza de piscina', FALSE, FALSE, 4),

            ('CERRAJERIA_MATERIAL', 'HIERRO', 'Hierro', TRUE, FALSE, 1),
            ('CERRAJERIA_MATERIAL', 'MULTILOCK', 'Multilock', TRUE, FALSE, 2),
            ('CERRAJERIA_MATERIAL', 'MADERA', 'Madera', TRUE, FALSE, 3),
            ('CERRAJERIA_MATERIAL', 'VIDRIO_ALUMINIO', 'Vidrio/Aluminio', TRUE, FALSE, 4),

            ('REPARACION', 'FILTRACIONES', 'Filtraciones/Impermeabilización', FALSE, FALSE, 1),
            ('REPARACION', 'TRABAJOS_ELECTRICOS', 'Trabajos eléctricos', FALSE, FALSE, 2),
            ('REPARACION', 'TRABAJOS_PLOMERIA', 'Trabajos de Plomería', FALSE, FALSE, 3),
            ('REPARACION', 'REPARACION_PUERTAS', 'Reemplazo o Reparación de Puertas',
             FALSE, FALSE, 4),
            ('REPARACION', 'REPARACION_VENTANAS', 'Reemplazo o Reparación de Ventanas',
             FALSE, FALSE, 5),
            ('REPARACION', 'TRABAJOS_CERCADO', 'Trabajos de Cercado', FALSE, FALSE, 6),
            ('REPARACION', 'REPARACION_TECHOS', 'Reparación de Techos', FALSE, FALSE, 7),
            ('REPARACION', 'REPARACION_PAREDES', 'Reparación de Paredes', FALSE, FALSE, 8),
            ('REPARACION', 'OTRAS_REPARACIONES', 'Otras Reparaciones', FALSE, TRUE, 9),

            ('INSPECCION_TECNICA', 'ELECTRICA', 'Inspección eléctrica', FALSE, FALSE, 1),
            ('INSPECCION_TECNICA', 'PLOMERIA', 'Inspección de plomería', FALSE, FALSE, 2),
            ('INSPECCION_TECNICA', 'AIRE_ACONDICIONADO', 'Inspección Aire Acondicionado',
             FALSE, FALSE, 3)
        ON CONFLICT (tipo_catalogo, codigo) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inspecciones.levantamiento_opcion")
