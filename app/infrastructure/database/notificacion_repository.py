"""Queries SQL del módulo de notificaciones usando asyncpg."""
from __future__ import annotations

import uuid
from typing import Any

import asyncpg

_ACTIVAS = ("NO_LEIDA",)


class NotificacionRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def list_for_user(
        self,
        email: str,
        roles: list[str],
        estados: list[str] | None,
        pagina: int,
        tamanio: int,
    ) -> tuple[list[asyncpg.Record], int]:
        estados_filtro = estados or list(_ACTIVAS)
        offset = (pagina - 1) * tamanio
        rows = await self._pool.fetch(
            """
            SELECT n.id_notificacion, n.tipo_notificacion, n.titulo, n.mensaje,
                   n.referencia_tipo, n.referencia_id, n.fecha_creacion,
                   n.creado_por AS creador, n.icono, n.path, n.modal,
                   CASE WHEN COALESCE(l.fue_silenciada, FALSE)
                        THEN 'SILENCIADA' ELSE 'NO_LEIDA' END AS estado,
                   COALESCE(l.fue_vista, FALSE) AS fue_vista,
                   l.fecha_vista
            FROM inspecciones.notificacion n
            LEFT JOIN inspecciones.notificacion_lectura l
                   ON l.id_notificacion = n.id_notificacion
                  AND l.email_lector = $1
            WHERE n.estado_notificacion = 'ACTIVA'
              AND (n.email_destinatario = $1 OR n.rol_destino = ANY($2::varchar[]))
              AND (CASE WHEN COALESCE(l.fue_silenciada, FALSE)
                        THEN 'SILENCIADA' ELSE 'NO_LEIDA' END) = ANY($3::varchar[])
            ORDER BY n.fecha_creacion DESC
            LIMIT $4 OFFSET $5
            """,
            email,
            roles,
            estados_filtro,
            tamanio,
            offset,
        )
        total: int = await self._pool.fetchval(
            """
            SELECT COUNT(*)
            FROM inspecciones.notificacion n
            LEFT JOIN inspecciones.notificacion_lectura l
                   ON l.id_notificacion = n.id_notificacion
                  AND l.email_lector = $1
            WHERE n.estado_notificacion = 'ACTIVA'
              AND (n.email_destinatario = $1 OR n.rol_destino = ANY($2::varchar[]))
              AND (CASE WHEN COALESCE(l.fue_silenciada, FALSE)
                        THEN 'SILENCIADA' ELSE 'NO_LEIDA' END) = ANY($3::varchar[])
            """,
            email,
            roles,
            estados_filtro,
        )
        return rows, total  # type: ignore[return-value]

    async def count_no_leidas(self, email: str, roles: list[str]) -> int:
        return await self._pool.fetchval(
            """
            SELECT COUNT(*)
            FROM inspecciones.notificacion n
            LEFT JOIN inspecciones.notificacion_lectura l
                   ON l.id_notificacion = n.id_notificacion
                  AND l.email_lector = $1
            WHERE n.estado_notificacion = 'ACTIVA'
              AND (n.email_destinatario = $1 OR n.rol_destino = ANY($2::varchar[]))
              AND l.id_notificacion IS NULL
            """,
            email,
            roles,
        )

    async def get_by_id(self, id_notificacion: uuid.UUID) -> asyncpg.Record | None:
        return await self._pool.fetchrow(
            """
            SELECT id_notificacion, rol_destino, email_destinatario, estado_notificacion
            FROM inspecciones.notificacion
            WHERE id_notificacion = $1
            """,
            id_notificacion,
        )

    async def marcar_vista(self, id_notificacion: uuid.UUID, email_lector: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO inspecciones.notificacion_lectura (
                id_notificacion, email_lector, fue_vista, fecha_vista
            ) VALUES ($1, $2, TRUE, NOW())
            ON CONFLICT (id_notificacion, email_lector)
            DO UPDATE SET fue_vista = TRUE, fecha_vista = NOW()
            """,
            id_notificacion,
            email_lector,
        )

    async def marcar_silenciada(self, id_notificacion: uuid.UUID, email_lector: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO inspecciones.notificacion_lectura (
                id_notificacion, email_lector, fue_silenciada, fecha_silenciada
            ) VALUES ($1, $2, TRUE, NOW())
            ON CONFLICT (id_notificacion, email_lector)
            DO UPDATE SET fue_silenciada = TRUE, fecha_silenciada = NOW()
            """,
            id_notificacion,
            email_lector,
        )

    async def marcar_vista_y_silenciada(
        self, id_notificacion: uuid.UUID, email_lector: str
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO inspecciones.notificacion_lectura (
                id_notificacion, email_lector,
                fue_vista, fecha_vista, fue_silenciada, fecha_silenciada
            ) VALUES ($1, $2, TRUE, NOW(), TRUE, NOW())
            ON CONFLICT (id_notificacion, email_lector)
            DO UPDATE SET fue_vista = TRUE, fecha_vista = NOW(),
                          fue_silenciada = TRUE, fecha_silenciada = NOW()
            """,
            id_notificacion,
            email_lector,
        )

    async def get_ultima_activa_por_referencia(
        self,
        email_destinatario: str,
        referencia_tipo: str,
        referencia_id: uuid.UUID,
        tipo_notificacion: str,
    ) -> uuid.UUID | None:
        """Id de la notificación activa más reciente para esta referencia y email.

        Usado por jobs recurrentes (p.ej. alertas de vencimiento) que crean una
        notificación nueva en cada corrida en vez de editar la anterior: antes de
        crear la de hoy, permite silenciar la más reciente que haya quedado activa,
        para que quede como historial en vez de amontonarse sin leer.
        """
        return await self._pool.fetchval(
            """
            SELECT n.id_notificacion
            FROM inspecciones.notificacion n
            WHERE n.email_destinatario = $1
              AND n.referencia_tipo = $2
              AND n.referencia_id = $3
              AND n.tipo_notificacion = $4
              AND n.estado_notificacion = 'ACTIVA'
            ORDER BY n.fecha_creacion DESC
            LIMIT 1
            """,
            email_destinatario,
            referencia_tipo,
            referencia_id,
            tipo_notificacion,
        )

    async def close_previous(
        self,
        rol_destino: str | None,
        email_destinatario: str | None,
        referencia_tipo: str,
        referencia_id: uuid.UUID,
        tipo_notificacion: str,
    ) -> None:
        await self._pool.execute(
            """
            UPDATE inspecciones.notificacion
            SET estado_notificacion = 'CERRADA', fecha_cerrada = NOW()
            WHERE (rol_destino = $1 OR email_destinatario = $2)
              AND referencia_tipo = $3
              AND referencia_id = $4
              AND tipo_notificacion = $5
              AND estado_notificacion = 'ACTIVA'
            """,
            rol_destino,
            email_destinatario,
            referencia_tipo,
            referencia_id,
            tipo_notificacion,
        )

    async def insert(self, notificacion: dict[str, Any]) -> asyncpg.Record:
        return await self._pool.fetchrow(  # type: ignore[return-value]
            """
            INSERT INTO inspecciones.notificacion (
                rol_destino, email_destinatario, tipo_notificacion,
                titulo, mensaje, referencia_tipo, referencia_id, creado_por
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id_notificacion
            """,
            notificacion["rol_destino"],
            notificacion["email_destinatario"],
            notificacion["tipo_notificacion"],
            notificacion["titulo"],
            notificacion["mensaje"],
            notificacion["referencia_tipo"],
            notificacion["referencia_id"],
            notificacion["creado_por"],
        )
