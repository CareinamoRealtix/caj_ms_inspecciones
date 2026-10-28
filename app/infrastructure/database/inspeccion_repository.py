"""Queries SQL contra el schema inspecciones usando asyncpg."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import asyncpg


@dataclass
class LevantamientoFinalizeResult:
    estado: Literal[
        "creado",
        "repetido",
        "no_encontrada",
        "conflicto_contenido",
        "ya_finalizada",
        "operacion_de_otra_inspeccion",
    ]
    id_levantamiento: uuid.UUID | None = None
    respuesta_previa: dict[str, Any] | None = None
    numero_inspeccion: int | None = None
    id_bien_inventario: uuid.UUID | None = None


# bien.estatus_bien_inventario: «Vendido». Esos bienes no se listan en /gestion ni /control.
ID_ESTATUS_BIEN_VENDIDO = 6


class InspeccionRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Catálogos
    # ------------------------------------------------------------------

    async def get_tipos_inspeccion(self) -> list[asyncpg.Record]:
        return await self._pool.fetch(  # type: ignore[return-value]
            "SELECT id_tipo_inspeccion AS id, nombre, descripcion, permite_descripcion_libre "
            "FROM inspecciones.tipo_inspeccion ORDER BY id_tipo_inspeccion"
        )

    async def get_periodicidades(self) -> list[asyncpg.Record]:
        return await self._pool.fetch(  # type: ignore[return-value]
            "SELECT id_periodicidad AS id, nombre, dias_vigencia "
            "FROM inspecciones.periodicidad ORDER BY id_periodicidad"
        )

    async def get_rutas(self) -> list[asyncpg.Record]:
        return await self._pool.fetch(  # type: ignore[return-value]
            "SELECT id, codigo, nombre FROM inspecciones.ruta ORDER BY nombre, codigo"
        )

    async def get_periodicidad_dias(self, id_periodicidad: int) -> int | None:
        return await self._pool.fetchval(
            "SELECT dias_vigencia FROM inspecciones.periodicidad "
            "WHERE id_periodicidad = $1",
            id_periodicidad,
        )

    async def get_catalogos_gestion(self) -> list[asyncpg.Record]:
        return await self._pool.fetch(  # type: ignore[return-value]
            """
            SELECT tipo_catalogo, id, id_padre, nombre
            FROM inspecciones.v_catalogos_gestion
            ORDER BY tipo_catalogo, nombre, id
            """
        )

    async def get_levantamiento_opciones_activas(self) -> list[asyncpg.Record]:
        return await self._pool.fetch(  # type: ignore[return-value]
            """
            SELECT tipo_catalogo, codigo, nombre, requiere_cantidad, permite_descripcion, orden
            FROM inspecciones.levantamiento_opcion
            WHERE es_activo
            UNION ALL
            SELECT tipo_servicio AS tipo_catalogo, codigo, nombre, requiere_cantidad,
                   permite_descripcion, orden
            FROM inspecciones.servicio
            WHERE es_activo
            ORDER BY tipo_catalogo, orden, nombre
            """
        )

    # ------------------------------------------------------------------
    # Inspección CRUD
    # ------------------------------------------------------------------

    async def get_active_inspeccion_by_bien_finca(
        self, id_bien_inventario: uuid.UUID, numero_finca: str
    ) -> asyncpg.Record | None:
        return await self._pool.fetchrow(  # type: ignore[return-value]
            """
            SELECT id_inspeccion, numero_inspeccion
            FROM inspecciones.inspeccion
            WHERE id_bien_inventario = $1
              AND numero_finca = $2
              AND activa = TRUE
            LIMIT 1
            """,
            id_bien_inventario,
            numero_finca.strip(),
        )

    async def insert_inspeccion(
        self,
        id_inspeccion: uuid.UUID,
        id_bien_inventario: uuid.UUID,
        numero_finca: str,
        ruta_id: uuid.UUID,
        ruta_nombre: str,
        id_tipo_inspeccion: int,
        id_periodicidad: int,
        email_inspector: str,
        fecha_programada: date,
        fecha_vencimiento: date | None,
        descripcion_tipo: str | None,
        creado_por: str | None,
    ) -> int:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO inspecciones.inspeccion (
                        id_inspeccion, id_bien_inventario, numero_finca, ruta_id, ruta_nombre,
                        id_tipo_inspeccion, id_periodicidad,
                        email_inspector,
                        fecha_programada, descripcion_tipo,
                        fecha_vencimiento, activa,
                        creado_por, origen
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                        TRUE, $12, 'WEB'
                    )
                    RETURNING numero_inspeccion
                    """,
                    id_inspeccion,
                    id_bien_inventario,
                    numero_finca,
                    ruta_id,
                    ruta_nombre,
                    id_tipo_inspeccion,
                    id_periodicidad,
                    email_inspector,
                    fecha_programada,
                    descripcion_tipo,
                    fecha_vencimiento,
                    creado_por,
                )

                # Mantener la asignación de ruta del bien+finca actualizada
                await conn.execute(
                    """
                    INSERT INTO inspecciones.bien_inventario_ruta (
                        id_bien_inventario, id_ruta, numero_finca
                    ) VALUES ($1, $2, $3)
                    ON CONFLICT (id_bien_inventario, numero_finca) DO UPDATE
                    SET id_ruta = EXCLUDED.id_ruta
                    """,
                    id_bien_inventario,
                    ruta_id,
                    numero_finca,
                )

        return row["numero_inspeccion"]  # type: ignore[index]

    async def insert_inspecciones_batch(
        self,
        inspecciones: list[dict[str, Any]],
        creado_por: str | None,
    ) -> list[asyncpg.Record]:
        if not inspecciones:
            return []
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetch(  # type: ignore[return-value]
                    """
                    INSERT INTO inspecciones.inspeccion (
                        id_inspeccion, id_bien_inventario, numero_finca, ruta_id, ruta_nombre,
                        id_tipo_inspeccion, id_periodicidad,
                        email_inspector,
                        fecha_programada, descripcion_tipo, fecha_vencimiento, activa,
                        creado_por, origen
                    )
                    SELECT batch.id_inspeccion,
                           batch.id_bien_inventario,
                           batch.numero_finca,
                           batch.ruta_id,
                           batch.ruta_nombre,
                           batch.id_tipo_inspeccion,
                           batch.id_periodicidad,
                           batch.email_inspector,
                           batch.fecha_programada,
                           batch.descripcion_tipo,
                           batch.fecha_vencimiento,
                           TRUE,
                           $12,
                           'WEB'
                    FROM UNNEST(
                        $1::uuid[], $2::uuid[], $3::varchar[], $4::uuid[], $5::varchar[],
                        $6::integer[], $7::integer[], $8::varchar[],
                        $9::date[], $10::varchar[], $11::date[]
                    ) AS batch(
                        id_inspeccion, id_bien_inventario, numero_finca, ruta_id, ruta_nombre,
                        id_tipo_inspeccion, id_periodicidad,
                        email_inspector,
                        fecha_programada, descripcion_tipo, fecha_vencimiento
                    )
                    RETURNING id_inspeccion, numero_inspeccion
                    """,
                    [item["id_inspeccion"] for item in inspecciones],
                    [item["id_bien_inventario"] for item in inspecciones],
                    [item["numero_finca"] for item in inspecciones],
                    [item["ruta_id"] for item in inspecciones],
                    [item["ruta_nombre"] for item in inspecciones],
                    [item["id_tipo_inspeccion"] for item in inspecciones],
                    [item["id_periodicidad"] for item in inspecciones],
                    [item["email_inspector"] for item in inspecciones],
                    [item["fecha_programada"] for item in inspecciones],
                    [item["descripcion_tipo"] for item in inspecciones],
                    [item["fecha_vencimiento"] for item in inspecciones],
                    creado_por,
                )

                # Actualizar asignaciones de ruta para cada bien+finca insertado
                for item in inspecciones:
                    await conn.execute(
                        """
                        INSERT INTO inspecciones.bien_inventario_ruta (
                            id_bien_inventario, id_ruta, numero_finca
                        ) VALUES ($1, $2, $3)
                        ON CONFLICT (id_bien_inventario, numero_finca) DO UPDATE
                        SET id_ruta = EXCLUDED.id_ruta
                        """,
                        item["id_bien_inventario"],
                        item["ruta_id"],
                        item["numero_finca"],
                    )

        return inserted

    async def get_inspeccion_by_id(self, id_inspeccion: uuid.UUID) -> asyncpg.Record | None:
        return await self._pool.fetchrow(  # type: ignore[return-value]
            """
            SELECT i.id_inspeccion, i.numero_inspeccion, i.id_bien_inventario, i.numero_finca,
                   i.ruta_id, i.ruta_nombre,
                   i.id_tipo_inspeccion, ti.nombre AS tipo_inspeccion,
                   i.descripcion_tipo, i.email_inspector,
                   i.id_periodicidad, p.nombre AS periodicidad, p.dias_vigencia,
                   i.fecha_programada, i.fecha_realizada,
                   i.fecha_vencimiento,
                   i.origen, i.activa,
                   CASE WHEN i.activa THEN 'Activa' ELSE 'Finalizada' END AS estado_inspeccion,
                   i.creado_por, i.fecha_creacion
            FROM inspecciones.inspeccion i
            JOIN inspecciones.tipo_inspeccion ti
                ON ti.id_tipo_inspeccion = i.id_tipo_inspeccion
            LEFT JOIN inspecciones.periodicidad p
                ON p.id_periodicidad = i.id_periodicidad
            WHERE i.id_inspeccion = $1
            """,
            id_inspeccion,
        )

    async def get_inspeccion_lifecycle(
        self, id_inspeccion: uuid.UUID
    ) -> asyncpg.Record | None:
        return await self._pool.fetchrow(  # type: ignore[return-value]
            """
            SELECT activa, fecha_realizada
            FROM inspecciones.inspeccion
            WHERE id_inspeccion = $1
            """,
            id_inspeccion,
        )

    async def update_inspeccion(
        self,
        id_inspeccion: uuid.UUID,
        ruta_id: uuid.UUID,
        ruta_nombre: str,
        id_tipo_inspeccion: int,
        id_periodicidad: int,
        email_inspector: str,
        fecha_programada: date,
        fecha_vencimiento: date | None,
        descripcion_tipo: str | None,
        modificado_por: str | None,
    ) -> int | None:
        row = await self._pool.fetchrow(
            """
            UPDATE inspecciones.inspeccion
            SET ruta_id = $1,
                ruta_nombre = $2,
                id_tipo_inspeccion = $3,
                id_periodicidad = $4,
                email_inspector = $5,
                fecha_programada = $6,
                descripcion_tipo = $7,
                fecha_vencimiento = $8,
                activa = TRUE,
                modificado_por = $9,
                fecha_modificacion = NOW()
            WHERE id_inspeccion = $10
            RETURNING numero_inspeccion
            """,
            ruta_id,
            ruta_nombre,
            id_tipo_inspeccion,
            id_periodicidad,
            email_inspector,
            fecha_programada,
            descripcion_tipo,
            fecha_vencimiento,
            modificado_por,
            id_inspeccion,
        )
        return row["numero_inspeccion"] if row else None

    async def upsert_bien_inventario_ruta(
        self,
        id_bien_inventario: uuid.UUID,
        id_ruta: uuid.UUID,
        numero_finca: str | None,
    ) -> None:
        """Inserta o actualiza la asignación de ruta para un bien+finca de inventario."""
        await self._pool.execute(
            """
            INSERT INTO inspecciones.bien_inventario_ruta (
                id_bien_inventario, id_ruta, numero_finca
            ) VALUES ($1, $2, $3)
            ON CONFLICT (id_bien_inventario, numero_finca) DO UPDATE
            SET id_ruta = EXCLUDED.id_ruta
            """,
            id_bien_inventario,
            id_ruta,
            numero_finca,
        )

    async def get_bien_inventario_rutas_for_bienes(
        self, ids: list[uuid.UUID]
    ) -> list[asyncpg.Record]:
        if not ids:
            return []
        return await self._pool.fetch(  # type: ignore[return-value]
            """
            SELECT bir.id_bien_inventario, bir.numero_finca,
                   bir.id_ruta, r.nombre AS ruta_nombre
            FROM inspecciones.bien_inventario_ruta bir
            JOIN inspecciones.ruta r ON r.id = bir.id_ruta
            WHERE bir.id_bien_inventario = ANY($1::uuid[])
            """,
            ids,
        )

    # ------------------------------------------------------------------
    # Histórico
    # ------------------------------------------------------------------

    async def get_historico_by_finca(
        self,
        numero_finca: str | None,
        pagina: int,
        tamanio: int,
        id_provincia: int | None = None,
        id_distrito: int | None = None,
        id_corregimiento: int | None = None,
        ruta: uuid.UUID | None = None,
        inspector: str | None = None,
        month_last_insp: str | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> tuple[list[asyncpg.Record], int]:
        filtros = (
            numero_finca,
            id_provincia,
            id_distrito,
            id_corregimiento,
            ruta,
            inspector,
            month_last_insp,
            fecha_desde,
            fecha_hasta,
        )
        if all(f is None for f in filtros):
            return [], 0

        offset = (pagina - 1) * tamanio

        conditions: list[str] = [
            "i.activa = FALSE",
            "i.fecha_realizada IS NOT NULL",
        ]
        params: list[Any] = []

        def add_condition(template: str, value: Any) -> None:
            params.append(value)
            conditions.append(template.format(parameter=f"${len(params)}"))

        if numero_finca is not None:
            escaped = (
                numero_finca.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            add_condition("i.numero_finca ILIKE {parameter} ESCAPE '\\'", f"%{escaped}%")
        if id_provincia is not None:
            add_condition("v.id_provincia = {parameter}", id_provincia)
        if id_distrito is not None:
            add_condition("v.id_distrito = {parameter}", id_distrito)
        if id_corregimiento is not None:
            add_condition("v.id_corregimiento = {parameter}", id_corregimiento)
        if ruta is not None:
            add_condition(
                """EXISTS (
                    SELECT 1
                    FROM inspecciones.bien_inventario_ruta bir
                    WHERE bir.id_bien_inventario = v.id_bien_inventario
                      AND bir.id_ruta = {parameter}
                )""",
                ruta,
            )
        if inspector is not None:
            add_condition("LOWER(i.email_inspector) = LOWER({parameter})", inspector)
        if month_last_insp is not None:
            add_condition(
                "i.fecha_realizada >= TO_DATE({parameter}, 'YYYY-MM')",
                month_last_insp,
            )
            add_condition(
                "i.fecha_realizada < TO_DATE({parameter}, 'YYYY-MM')"
                " + INTERVAL '1 month'",
                month_last_insp,
            )
        if fecha_desde is not None:
            add_condition("i.fecha_realizada >= {parameter}", fecha_desde)
        if fecha_hasta is not None:
            add_condition("i.fecha_realizada <= {parameter}", fecha_hasta)

        where_sql = " AND ".join(conditions)
        data_params = [*params, tamanio, offset]
        limit_parameter = f"${len(params) + 1}"
        offset_parameter = f"${len(params) + 2}"

        total: int = await self._pool.fetchval(
            f"""
            SELECT COUNT(*)
            FROM inspecciones.inspeccion i
            JOIN inspecciones.v_consulta_inventario v
                ON v.id_bien_inventario = i.id_bien_inventario
            WHERE {where_sql}
            """,
            *params,
        )
        rows = await self._pool.fetch(
            f"""
            SELECT
                i.id_inspeccion, i.id_bien_inventario, i.numero_finca,
                i.numero_inspeccion,
                i.email_inspector, i.fecha_programada, i.fecha_realizada,
                i.fecha_vencimiento, i.fecha_creacion, i.fecha_modificacion,
                i.activa,
                CASE WHEN i.activa THEN 'Activa' ELSE 'Finalizada' END AS estado_inspeccion
            FROM inspecciones.inspeccion i
            JOIN inspecciones.v_consulta_inventario v
                ON v.id_bien_inventario = i.id_bien_inventario
            WHERE {where_sql}
            ORDER BY i.fecha_programada DESC, i.numero_inspeccion DESC
            LIMIT {limit_parameter} OFFSET {offset_parameter}
            """,
            *data_params,
        )
        return rows, total  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Detalle completo
    # ------------------------------------------------------------------

    async def get_detalle(self, id_inspeccion: uuid.UUID) -> asyncpg.Record | None:
        return await self._pool.fetchrow(  # type: ignore[return-value]
            """
            SELECT i.id_inspeccion, i.numero_inspeccion, i.numero_finca, i.id_bien_inventario,
                   i.ruta_id, i.ruta_nombre,
                   i.fecha_programada, i.fecha_realizada,
                   ti.nombre AS tipo_inspeccion, i.descripcion_tipo,
                   i.email_inspector,
                   CASE WHEN i.activa THEN 'Activa' ELSE 'Finalizada' END AS estado_inspeccion,
                   CASE WHEN i.activa THEN '#28a745' ELSE '#007bff' END AS color_badge,
                   i.origen,
                   v.provincia, v.distrito, v.corregimiento, v.barriada_sector,
                   v.direccion, v.numero_lote,
                   l.id_levantamiento,
                   ST_Y(l.geom_levantamiento)::text || ',' || ST_X(l.geom_levantamiento)::text
                       AS coordenadas,
                   l.condicion_bien, l.estado_ocupacion,
                   l.nombre_ocupante, l.tipo_identificacion_ocup, l.numero_identificacion_ocup,
                   l.numero_contacto_ocupante, l.comentarios_ocupante,
                   l.puertas, l.tipos_ventanas, l.servicios_publicos,
                   l.distribucion_inmueble, l.servicios_requeridos,
                   l.inspeccion_tecnica_req, l.tipos_inspeccion_tecnica,
                   l.motivacion, l.url_firma_inspector, l.observaciones,
                   l.fecha_levantamiento
            FROM inspecciones.inspeccion i
            JOIN inspecciones.tipo_inspeccion ti
                ON ti.id_tipo_inspeccion = i.id_tipo_inspeccion
            LEFT JOIN inspecciones.v_consulta_inventario v
                ON v.id_bien_inventario = i.id_bien_inventario
            LEFT JOIN inspecciones.levantamiento_inspeccion l
                ON l.id_inspeccion = i.id_inspeccion
            WHERE i.id_inspeccion = $1
            """,
            id_inspeccion,
        )

    async def get_fotografias_by_inspeccion(
        self, id_inspeccion: uuid.UUID
    ) -> list[asyncpg.Record]:
        return await self._pool.fetch(  # type: ignore[return-value]
            """
            SELECT f.id_fotografia, f.url_s3, f.nombre_archivo,
                   f.es_visible_geovisor, f.es_foto_principal, f.orden
            FROM inspecciones.inspeccion_fotografia f
            JOIN inspecciones.levantamiento_inspeccion l
                ON l.id_levantamiento = f.id_levantamiento
            WHERE l.id_inspeccion = $1
            ORDER BY f.orden, f.fecha_creacion
            """,
            id_inspeccion,
        )

    # ------------------------------------------------------------------
    # Fotografías PATCH
    # ------------------------------------------------------------------

    async def update_fotografias(
        self,
        id_inspeccion: uuid.UUID,
        fotografias: list[dict[str, Any]],
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                nueva_principal = next(
                    (f["id_fotografia"] for f in fotografias if f["es_foto_principal"]), None
                )
                if nueva_principal is not None:
                    # Libera antes al índice único parcial uq_foto_principal: si la fila que
                    # hoy es principal no se limpia primero, el UPDATE de abajo que marca la
                    # nueva colisiona con ella (violación de unicidad transitoria).
                    await conn.execute(
                        """
                        UPDATE inspecciones.inspeccion_fotografia f
                        SET es_foto_principal = FALSE
                        FROM inspecciones.levantamiento_inspeccion l
                        WHERE f.id_levantamiento = l.id_levantamiento
                          AND l.id_inspeccion = $1
                          AND f.es_foto_principal = TRUE
                          AND f.id_fotografia != $2
                        """,
                        id_inspeccion,
                        nueva_principal,
                    )
                for foto in fotografias:
                    await conn.execute(
                        """
                        UPDATE inspecciones.inspeccion_fotografia f
                        SET es_visible_geovisor = $1,
                            es_foto_principal   = $2
                        FROM inspecciones.levantamiento_inspeccion l
                        WHERE f.id_levantamiento = l.id_levantamiento
                          AND l.id_inspeccion = $3
                          AND f.id_fotografia = $4
                        """,
                        foto["es_visible_geovisor"],
                        foto["es_foto_principal"],
                        id_inspeccion,
                        foto["id_fotografia"],
                    )

    # ------------------------------------------------------------------
    # Levantamiento (upsert)
    # ------------------------------------------------------------------

    async def finalizar_levantamiento(
        self,
        id_inspeccion: uuid.UUID,
        id_operacion: uuid.UUID,
        contenido_hash: str,
        data: dict[str, Any],
        fecha_levantamiento: date,
        creado_por: str | None,
        fotografias: list[dict[str, Any]] | None = None,
    ) -> LevantamientoFinalizeResult:
        """Finaliza un levantamiento de forma transaccional e idempotente.

        Bloquea la fila de la inspección (`FOR UPDATE`) antes de decidir nada: eso
        serializa cualquier par de finalizaciones concurrentes sobre la misma
        inspección, sea con el mismo `id_operacion` (reintento) o distinto (una
        segunda finalización genuina).
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inspeccion = await conn.fetchrow(
                    "SELECT fecha_realizada, numero_inspeccion, id_bien_inventario "
                    "FROM inspecciones.inspeccion WHERE id_inspeccion = $1 FOR UPDATE",
                    id_inspeccion,
                )
                if inspeccion is None:
                    return LevantamientoFinalizeResult(estado="no_encontrada")

                operacion_previa = await conn.fetchrow(
                    "SELECT id_inspeccion, contenido_hash, respuesta "
                    "FROM inspecciones.levantamiento_operacion WHERE id_operacion = $1",
                    id_operacion,
                )
                if operacion_previa is not None:
                    if operacion_previa["id_inspeccion"] != id_inspeccion:
                        # id_operacion es la PRIMARY KEY de la tabla, así que es global: un
                        # cliente que reutiliza el mismo id_operacion para otra inspección no
                        # debe recibir una respuesta "repetido" que en realidad pertenece a esa
                        # otra inspección y nunca tocó la fila bloqueada arriba.
                        return LevantamientoFinalizeResult(estado="operacion_de_otra_inspeccion")
                    if operacion_previa["contenido_hash"] == contenido_hash:
                        return LevantamientoFinalizeResult(
                            estado="repetido",
                            respuesta_previa=json.loads(operacion_previa["respuesta"]),
                        )
                    return LevantamientoFinalizeResult(estado="conflicto_contenido")

                if inspeccion["fecha_realizada"] is not None:
                    return LevantamientoFinalizeResult(estado="ya_finalizada")

                row = await conn.fetchrow(
                    """
                    INSERT INTO inspecciones.levantamiento_inspeccion (
                        id_inspeccion, geom_levantamiento, condicion_bien, estado_ocupacion,
                        nombre_ocupante, tipo_identificacion_ocup, numero_identificacion_ocup,
                        numero_contacto_ocupante, comentarios_ocupante,
                        puertas, tipos_ventanas, servicios_publicos,
                        distribucion_inmueble, servicios_requeridos,
                        inspeccion_tecnica_req, tipos_inspeccion_tecnica,
                        motivacion, url_firma_inspector, observaciones,
                        fecha_levantamiento, creado_por
                    ) VALUES (
                        $1,
                        CASE WHEN $2::text IS NULL THEN NULL
                             ELSE ST_SetSRID(ST_MakePoint(
                                 split_part($2::text, ',', 2)::float8,
                                 split_part($2::text, ',', 1)::float8), 4326)
                        END,
                        $3, $4, $5, $6, $7, $8, $9,
                        $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14::jsonb,
                        $15, $16::jsonb, $17, $18, $19, $20, $21
                    )
                    ON CONFLICT (id_inspeccion) DO NOTHING
                    RETURNING id_levantamiento
                    """,
                    id_inspeccion,
                    data.get("coordenadas"),
                    data["condicion_bien"],
                    data["estado_ocupacion"],
                    data.get("nombre_ocupante"),
                    data.get("tipo_identificacion_ocup"),
                    data.get("numero_identificacion_ocup"),
                    data.get("numero_contacto_ocupante"),
                    data.get("comentarios_ocupante"),
                    _jsonb(data.get("puertas")),
                    _jsonb(data.get("tipos_ventanas")),
                    _jsonb(data.get("servicios_publicos")),
                    _jsonb(data.get("distribucion_inmueble")),
                    _jsonb(data.get("servicios_requeridos")),
                    data.get("inspeccion_tecnica_req", False),
                    _jsonb(data.get("tipos_inspeccion_tecnica")),
                    data.get("motivacion"),
                    data.get("url_firma_inspector"),
                    data.get("observaciones"),
                    fecha_levantamiento,
                    creado_por,
                )
                if row is None:
                    return LevantamientoFinalizeResult(estado="ya_finalizada")

                id_levantamiento: uuid.UUID = row["id_levantamiento"]

                for orden, foto in enumerate(fotografias or []):
                    await conn.execute(
                        """
                        INSERT INTO inspecciones.inspeccion_fotografia (
                            id_levantamiento, url_s3, nombre_archivo,
                            es_visible_geovisor, es_foto_principal, orden
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        id_levantamiento,
                        foto["url"],
                        foto.get("nombre_archivo"),
                        foto.get("es_visible_geovisor", False),
                        foto.get("es_foto_principal", False),
                        foto.get("orden") if foto.get("orden") is not None else orden,
                    )

                await conn.execute(
                    """
                    UPDATE inspecciones.inspeccion AS i
                    SET fecha_realizada      = $1,
                        fecha_vencimiento    = $1::date + (
                            SELECT p.dias_vigencia
                            FROM inspecciones.periodicidad p
                            WHERE p.id_periodicidad = i.id_periodicidad
                        ),
                        activa               = FALSE,
                        modificado_por       = $2,
                        fecha_modificacion   = NOW()
                    WHERE i.id_inspeccion = $3
                    """,
                    fecha_levantamiento,
                    creado_por,
                    id_inspeccion,
                )

                respuesta = {
                    "id_levantamiento": str(id_levantamiento),
                    "id_inspeccion": str(id_inspeccion),
                    "estado_inspeccion": "Finalizada",
                    "mensaje": "Levantamiento finalizado correctamente",
                }
                await conn.execute(
                    """
                    INSERT INTO inspecciones.levantamiento_operacion (
                        id_operacion, id_inspeccion, contenido_hash, id_levantamiento,
                        respuesta, creado_por
                    ) VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                    """,
                    id_operacion,
                    id_inspeccion,
                    contenido_hash,
                    id_levantamiento,
                    json.dumps(respuesta),
                    creado_por,
                )

        return LevantamientoFinalizeResult(
            estado="creado",
            id_levantamiento=id_levantamiento,
            numero_inspeccion=inspeccion["numero_inspeccion"],
            id_bien_inventario=inspeccion["id_bien_inventario"],
        )

    # ------------------------------------------------------------------
    # Gestión — inventario leído mediante el contrato de vista del servicio
    # ------------------------------------------------------------------

    async def get_inventario(
        self,
        *,
        pagina: int,
        tamanio: int,
        numero_finca: str | None = None,
        id_estatus_bien: int | None = None,
        id_provincia: int | None = None,
        id_distrito: int | None = None,
        id_corregimiento: int | None = None,
        nuevo_ingreso: bool = False,
        requiere_inspeccion_finalizada: bool = False,
        alerta: str | None = None,
        ruta: uuid.UUID | None = None,
        inspector: str | None = None,
        month_last_insp: str | None = None,
        month_expiration: str | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> tuple[list[asyncpg.Record], int]:
        conditions: list[str] = []
        params: list[Any] = []

        def add_condition(template: str, value: Any) -> None:
            params.append(value)
            conditions.append(template.format(parameter=f"${len(params)}"))

        def ultima_inspeccion_completada_sql(column: str) -> str:
            # Última inspección ya realizada (fecha_realizada) y no activa
            # (activa = FALSE) del bien. NULL si el bien no tiene ninguna.
            return f"""(
                SELECT completed_i.{column}
                FROM inspecciones.inspeccion completed_i
                WHERE completed_i.id_bien_inventario = v.id_bien_inventario
                  AND completed_i.fecha_realizada IS NOT NULL
                  AND completed_i.activa = FALSE
                ORDER BY completed_i.fecha_realizada DESC,
                         completed_i.numero_inspeccion DESC
                LIMIT 1
            )"""

        ultima_fecha_vencimiento_sql = ultima_inspeccion_completada_sql("fecha_vencimiento")
        ultima_fecha_realizada_sql = ultima_inspeccion_completada_sql("fecha_realizada")

        conditions.append("v.es_activo = TRUE")
        # IS DISTINCT FROM conserva los bienes sin estatus (NULL), que `<>` descartaría.
        conditions.append(f"v.id_estatus_bien IS DISTINCT FROM {ID_ESTATUS_BIEN_VENDIDO}")
        conditions.append(
            "(v.estado_inventario IS NULL OR LOWER(v.estado_inventario) <> 'borrador')"
        )
        finca_parameter: str | None = None
        if numero_finca is not None:
            finca_parameter = f"${len(params) + 1}"
            add_condition(
                """(
                    v.numero_finca ILIKE {parameter}
                    OR EXISTS (
                        SELECT 1
                        FROM UNNEST(v.numeros_finca) AS nf(numero)
                        WHERE nf.numero ILIKE {parameter}
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM inspecciones.inspeccion finca_i
                        WHERE finca_i.id_bien_inventario = v.id_bien_inventario
                          AND finca_i.numero_finca ILIKE {parameter}
                    )
                )""",
                f"%{numero_finca}%",
            )
        if id_estatus_bien is not None:
            add_condition("v.id_estatus_bien = {parameter}", id_estatus_bien)
        if id_provincia is not None:
            add_condition("v.id_provincia = {parameter}", id_provincia)
        if id_distrito is not None:
            add_condition("v.id_distrito = {parameter}", id_distrito)
        if id_corregimiento is not None:
            add_condition("v.id_corregimiento = {parameter}", id_corregimiento)
        if nuevo_ingreso:
            conditions.append(
                """NOT EXISTS (
                    SELECT 1
                    FROM inspecciones.inspeccion i
                    WHERE i.id_bien_inventario = v.id_bien_inventario
                )"""
            )
        elif not requiere_inspeccion_finalizada:
            # In non-nuevo_ingreso mode include bienes que have any inspection
            # (we'll order those with fecha_vencimiento first, then NULLs).
            conditions.append(
                """EXISTS (
                    SELECT 1
                    FROM inspecciones.inspeccion i
                    WHERE i.id_bien_inventario = v.id_bien_inventario
                )"""
            )
        # requiere_inspeccion_finalizada=True (/control): sin restricción de existencia,
        # incluye todos los bienes activos tengan o no inspecciones registradas.
        if alerta is not None:
            comparison = {
                "TERMINO": "> CURRENT_DATE + INTERVAL '10 days'",
                "VENCIDA": "< CURRENT_DATE",
                "PROXIMA": (
                    "BETWEEN CURRENT_DATE AND "
                    "CURRENT_DATE + INTERVAL '10 days'"
                ),
            }[alerta]
            conditions.append(f"{ultima_fecha_vencimiento_sql} {comparison}")
        if ruta is not None:
            add_condition(
                """EXISTS (
                    SELECT 1
                    FROM inspecciones.bien_inventario_ruta bir
                    WHERE bir.id_bien_inventario = v.id_bien_inventario
                      AND bir.id_ruta = {parameter}
                )""",
                ruta,
            )
        if inspector is not None:
            add_condition(
                """(
                    SELECT i.email_inspector
                    FROM inspecciones.inspeccion i
                    WHERE i.id_bien_inventario = v.id_bien_inventario
                    ORDER BY i.numero_inspeccion DESC
                    LIMIT 1
                ) = {parameter}""",
                inspector,
            )
        if month_last_insp is not None:
            add_condition(
                f"{ultima_fecha_realizada_sql} >= TO_DATE({{parameter}}, 'YYYY-MM')",
                month_last_insp,
            )
            add_condition(
                f"{ultima_fecha_realizada_sql} < TO_DATE({{parameter}}, 'YYYY-MM')"
                " + INTERVAL '1 month'",
                month_last_insp,
            )
        if month_expiration is not None:
            add_condition(
                f"{ultima_fecha_vencimiento_sql} >= TO_DATE({{parameter}}, 'YYYY-MM')",
                month_expiration,
            )
            add_condition(
                f"{ultima_fecha_vencimiento_sql} < TO_DATE({{parameter}}, 'YYYY-MM')"
                " + INTERVAL '1 month'",
                month_expiration,
            )
        if fecha_desde is not None:
            add_condition(f"{ultima_fecha_realizada_sql} >= {{parameter}}", fecha_desde)
        if fecha_hasta is not None:
            add_condition(f"{ultima_fecha_realizada_sql} <= {{parameter}}", fecha_hasta)

        where_sql = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        data_params = [*params, tamanio, (pagina - 1) * tamanio]
        limit_parameter = f"${len(params) + 1}"
        offset_parameter = f"${len(params) + 2}"

        # La paginación es por (bien, finca): cada fila de la página es un ítem de la
        # respuesta. Un bien con varias fincas aporta una fila por finca.
        fincas_inspeccion_sql = """SELECT NULLIF(BTRIM(finca_i.numero_finca), '') AS numero
                    FROM inspecciones.inspeccion finca_i
                    WHERE finca_i.id_bien_inventario = v.id_bien_inventario"""
        fincas_inventario_sql = """SELECT NULLIF(BTRIM(inv.numero), '') AS numero
                    FROM UNNEST(
                        CASE
                            WHEN COALESCE(CARDINALITY(v.numeros_finca), 0) > 0
                                THEN v.numeros_finca::text[]
                            ELSE ARRAY[v.numero_finca::text]
                        END
                    ) AS inv(numero)"""
        if finca_parameter is not None or requiere_inspeccion_finalizada:
            # Con filtro de finca o en /control se emiten todas las fincas del bien
            # (inventario + inspecciones).
            fincas_candidatas_sql = (
                f"{fincas_inventario_sql} UNION {fincas_inspeccion_sql}"
            )
        else:
            # Sin filtro: las fincas con inspección; si no hay, las del inventario.
            fincas_candidatas_sql = f"""{fincas_inspeccion_sql}
                    AND NULLIF(BTRIM(finca_i.numero_finca), '') IS NOT NULL
                    UNION
                    {fincas_inventario_sql}
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM inspecciones.inspeccion finca_x
                        WHERE finca_x.id_bien_inventario = v.id_bien_inventario
                          AND NULLIF(BTRIM(finca_x.numero_finca), '') IS NOT NULL
                    )"""
        finca_filter_sql = (
            f"""AND (
                    v.numero_finca ILIKE {finca_parameter}
                    OR fc.numero ILIKE {finca_parameter}
                )"""
            if finca_parameter is not None
            else ""
        )
        fincas_join_sql = f"""CROSS JOIN LATERAL (
                SELECT DISTINCT fc.numero AS numero_finca_item
                FROM ({fincas_candidatas_sql}) AS fc
                WHERE fc.numero IS NOT NULL
                {finca_filter_sql}
            ) fi"""

        order_sql = (
            """(
                SELECT MAX(active_i.fecha_programada)
                FROM inspecciones.inspeccion active_i
                WHERE active_i.id_bien_inventario = v.id_bien_inventario
                  AND active_i.activa = TRUE
            ) DESC NULLS LAST"""
            if nuevo_ingreso
            else f"""CASE
                WHEN {ultima_fecha_vencimiento_sql} IS NULL THEN 3
                WHEN {ultima_fecha_vencimiento_sql} < CURRENT_DATE THEN 0
                WHEN {ultima_fecha_vencimiento_sql} <= CURRENT_DATE + INTERVAL '10 days' THEN 1
                ELSE 2
            END,
            {ultima_fecha_vencimiento_sql} ASC NULLS LAST"""
        )

        data_sql = f"""
            SELECT
                v.id_bien_inventario,
                v.id_bien,
                v.no_registro,
                v.numero_finca,
                fi.numero_finca_item,
                v.numeros_finca,
                v.nombre_deudor,
                v.numero_prestamo,
                v.id_tipo_propiedad,
                v.tipo_propiedad,
                v.id_provincia,
                v.provincia,
                v.id_distrito,
                v.distrito,
                v.id_corregimiento,
                v.corregimiento,
                v.barriada_sector,
                v.direccion,
                v.numero_lote,
                v.latitud,
                v.longitud,
                v.url_ubicacion_geoespacial,
                v.monto_adjudicado,
                v.valor_avaluo,
                v.estatus_bien,
                v.color_badge,
                v.estado_inventario,
                v.oficinista,
                v.usuario_registrador,
                v.fecha_recibido_inventario,
                v.fecha_creacion,
                {ultima_fecha_vencimiento_sql} AS fecha_vencimiento_orden
            FROM inspecciones.v_consulta_inventario v
            {fincas_join_sql}
            {where_sql}
            ORDER BY {order_sql},
            v.fecha_ingreso_inventario DESC NULLS LAST,
            v.no_registro DESC,
            fi.numero_finca_item
            LIMIT {limit_parameter} OFFSET {offset_parameter}
        """
        count_sql = f"""
            SELECT COUNT(*)
            FROM inspecciones.v_consulta_inventario v
            {fincas_join_sql}
            {where_sql}
        """

        rows = await self._pool.fetch(data_sql, *data_params)
        total: int = await self._pool.fetchval(count_sql, *params)
        return rows, total  # type: ignore[return-value]

    async def get_active_inspections_for_bienes(
        self, ids: list[uuid.UUID]
    ) -> list[asyncpg.Record]:
        if not ids:
            return []
        return await self._pool.fetch(  # type: ignore[return-value]
            """
                        SELECT DISTINCT ON (i.id_bien_inventario, i.numero_finca)
                                     i.id_bien_inventario,
                                     i.numero_finca,
                                     i.id_inspeccion, i.fecha_programada,
                                     i.fecha_vencimiento,
                                     i.ruta_id, i.ruta_nombre,
                                     i.id_periodicidad, p.nombre AS periodicidad,
                                     i.email_inspector,
                                     'Activa'::varchar AS estado_inspeccion,
                                     '#28a745'::varchar AS color_badge,
                                     ti.nombre AS tipo_inspeccion, i.descripcion_tipo
                        FROM inspecciones.inspeccion i
                        LEFT JOIN inspecciones.periodicidad p
                                ON p.id_periodicidad = i.id_periodicidad
                        LEFT JOIN inspecciones.tipo_inspeccion ti
                                ON ti.id_tipo_inspeccion = i.id_tipo_inspeccion
                        WHERE i.id_bien_inventario = ANY($1::uuid[])
                            AND i.activa = TRUE
                        ORDER BY i.id_bien_inventario,
                                         i.numero_finca,
                                         i.fecha_programada DESC,
                                         i.numero_inspeccion DESC,
                                         i.id_inspeccion DESC
            """,
            ids,
        )

    async def get_active_batch_targets_for_bienes(
        self, ids: list[uuid.UUID]
    ) -> list[asyncpg.Record]:
        if not ids:
            return []
        return await self._pool.fetch(  # type: ignore[return-value]
            """
            SELECT DISTINCT ON (i.id_bien_inventario, i.numero_finca)
                   i.id_bien_inventario,
                   i.numero_finca,
                   i.id_inspeccion,
                   i.numero_inspeccion
            FROM inspecciones.inspeccion i
            WHERE i.id_bien_inventario = ANY($1::uuid[])
              AND i.activa = TRUE
            ORDER BY i.id_bien_inventario,
                     i.numero_finca,
                     i.fecha_programada DESC,
                     i.numero_inspeccion DESC,
                     i.id_inspeccion DESC
            """,
            ids,
        )

    async def get_sincronizacion_inspecciones(self, email_inspector: str) -> list[asyncpg.Record]:
        """Inspecciones programadas desde hoy en adelante de un inspector, con finca y precargue.

        `ul` (último levantamiento) se resuelve por LATERAL: la última inspección con
        estado Finalizado para la misma combinación id_bien_inventario + numero_finca
        de la inspección programada (no de cualquier finca del mismo bien).
        """
        return await self._pool.fetch(  # type: ignore[return-value]
            """
            SELECT
                i.id_inspeccion, i.numero_inspeccion, i.fecha_programada,
                i.fecha_vencimiento, i.origen,
                i.id_tipo_inspeccion, i.descripcion_tipo, i.id_periodicidad,
                i.ruta_id, i.ruta_nombre,
                i.id_bien_inventario, i.numero_finca,

                v.id_bien, v.numeros_finca, v.nombre_deudor, v.numero_prestamo,
                v.tipo_propiedad, v.direccion, v.provincia, v.distrito, v.corregimiento,
                v.barriada_sector, v.numero_lote, v.latitud, v.longitud,
                v.url_ubicacion_geoespacial, v.id_estatus_bien, v.estatus_bien,
                v.color_badge, v.id_estado_inventario, v.estado_inventario,

                ul.id_inspeccion AS ul_id_inspeccion,
                ul.numero_inspeccion AS ul_numero_inspeccion,
                ul.fecha_levantamiento AS ul_fecha_levantamiento,
                ul.coordenadas AS ul_coordenadas,
                ul.condicion_bien AS ul_condicion_bien,
                ul.estado_ocupacion AS ul_estado_ocupacion,
                ul.nombre_ocupante AS ul_nombre_ocupante,
                ul.tipo_identificacion_ocup AS ul_tipo_identificacion_ocup,
                ul.numero_identificacion_ocup AS ul_numero_identificacion_ocup,
                ul.numero_contacto_ocupante AS ul_numero_contacto_ocupante,
                ul.comentarios_ocupante AS ul_comentarios_ocupante,
                ul.puertas AS ul_puertas,
                ul.tipos_ventanas AS ul_tipos_ventanas,
                ul.distribucion_inmueble AS ul_distribucion_inmueble,
                ul.servicios_publicos AS ul_servicios_publicos,
                ul.observaciones AS ul_observaciones
            FROM inspecciones.inspeccion i
            LEFT JOIN inspecciones.v_consulta_inventario v
                ON v.id_bien_inventario = i.id_bien_inventario
            LEFT JOIN LATERAL (
                SELECT completed_i.id_inspeccion, completed_i.numero_inspeccion,
                       l.fecha_levantamiento,
                       ST_Y(l.geom_levantamiento)::text || ',' || ST_X(l.geom_levantamiento)::text
                           AS coordenadas,
                       l.condicion_bien,
                       l.estado_ocupacion, l.nombre_ocupante,
                       l.tipo_identificacion_ocup, l.numero_identificacion_ocup,
                       l.numero_contacto_ocupante, l.comentarios_ocupante,
                       l.puertas, l.tipos_ventanas,
                       l.distribucion_inmueble, l.servicios_publicos, l.observaciones
                FROM inspecciones.inspeccion completed_i
                JOIN inspecciones.levantamiento_inspeccion l
                    ON l.id_inspeccion = completed_i.id_inspeccion
                WHERE completed_i.id_bien_inventario = i.id_bien_inventario
                  AND completed_i.numero_finca = i.numero_finca
                  AND completed_i.activa = FALSE
                  AND completed_i.fecha_realizada IS NOT NULL
                ORDER BY completed_i.fecha_realizada DESC, completed_i.numero_inspeccion DESC
                LIMIT 1
            ) ul ON TRUE
            WHERE i.email_inspector = $1
              AND i.fecha_programada >= CURRENT_DATE
              AND i.activa = TRUE
            ORDER BY i.fecha_programada, i.numero_inspeccion
            """,
            email_inspector,
        )

    async def get_latest_completed_inspections_for_bienes(
        self, ids: list[uuid.UUID]
    ) -> list[asyncpg.Record]:
        if not ids:
            return []
        return await self._pool.fetch(  # type: ignore[return-value]
            """
            SELECT DISTINCT ON (i.id_bien_inventario, i.numero_finca)
                   i.id_bien_inventario,
                   i.numero_finca,
                   i.numero_inspeccion,
                   i.fecha_realizada,
                   i.fecha_vencimiento
            FROM inspecciones.inspeccion i
            WHERE i.id_bien_inventario = ANY($1::uuid[])
              AND i.fecha_realizada IS NOT NULL
              AND i.activa = FALSE
            ORDER BY i.id_bien_inventario,
                     i.numero_finca,
                     i.fecha_realizada DESC,
                     i.numero_inspeccion DESC
            """,
            ids,
        )


def _jsonb(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)
