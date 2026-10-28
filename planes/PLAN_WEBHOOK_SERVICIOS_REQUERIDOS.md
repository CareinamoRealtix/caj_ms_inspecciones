# Plan: Callback a ms-órdenes-de-servicio al finalizar el levantamiento

## 1. Objetivo

Cuando se finaliza un levantamiento (`POST /{id_inspeccion}/levantamiento`) y el inspector marcó
`servicios_requeridos`, notificar al microservicio de órdenes de servicio llamando a su webhook
(hoy `http://161.97.86.251:8002/v1/requerimientos/webhook-inspecciones`, dado por el otro
desarrollador) con el detalle de esos servicios.

Por ahora el disparador sigue siendo el endpoint directo (`ENABLE_DIRECT_LEVANTAMIENTO_ENDPOINT`).
El plan coloca el callback en la capa de aplicación (`InspeccionService.finalizar_levantamiento`),
no en el router, precisamente para que cuando ese trigger cambie a un job de AWS Batch/Lambda más
adelante, la llamada al webhook siga funcionando sin tocarla — el job solo necesitará invocar el
mismo método de servicio (directamente o vía un nuevo endpoint interno), y el callback ya estará
adentro.

## 2. Lo que ya existe (sí tienes catálogo, con matices)

- `inspecciones.levantamiento_opcion` (creada en
  [`20260908_0033_create_levantamiento_opcion.py`](migrations/versions/20260908_0033_create_levantamiento_opcion.py))
  es el catálogo local de opciones del formulario, agrupado por `tipo_catalogo`.
- El campo `servicios_requeridos` del levantamiento (`list[SeleccionOpcion]`, con `codigo`,
  `cantidad` opcional y `descripcion` opcional) valida sus códigos contra la **unión** de tres
  grupos del catálogo — ver
  [`levantamiento_validacion.py:90-96`](app/application/levantamiento_validacion.py#L90-L96):
  - `LIMPIEZA`: INTERNA, EXTERNA, RETIRO_ENSERES, LIMPIEZA_PISCINA
  - `CERRAJERIA_MATERIAL`: HIERRO, MULTILOCK, MADERA, VIDRIO_ALUMINIO
  - `REPARACION`: FILTRACIONES, TRABAJOS_ELECTRICOS, TRABAJOS_PLOMERIA, REPARACION_PUERTAS,
    REPARACION_VENTANAS, TRABAJOS_CERCADO, REPARACION_TECHOS, REPARACION_PAREDES,
    OTRAS_REPARACIONES
- Cada opción del catálogo tiene `codigo` (el que llega en `servicios_requeridos[].codigo`),
  `nombre` (etiqueta legible, ej. "Limpieza de piscina") y `permite_descripcion` (si el frontend
  puede pedir texto libre para esa opción específica — hoy solo `OTRAS_REPARACIONES` y
  `VENTANA_TIPO.OTROS` lo tienen en `TRUE`).
- El endpoint `GET /levantamiento/catalogos` expone estos tres grupos (junto con los demás) para
  que el frontend/app móvil construya el formulario.

**Conclusión:** sí tienes de dónde sacar `tipo_servicio` (el `tipo_catalogo` de cada selección) y
una `subcategoria` legible (el `nombre` de la opción en el catálogo). Lo que **no tienes hoy** es
una `motivacion` de texto libre por cada servicio requerido de forma consistente — ver punto 3.

## 3. Cosas raras / decisiones que hay que tomar antes de programar

1. **`motivacion` por servicio no se captura hoy de forma general.** `SeleccionOpcion.descripcion`
   solo se acepta cuando `permite_descripcion = TRUE` en el catálogo, y hoy eso solo aplica a
   `OTRAS_REPARACIONES` (y a `VENTANA_TIPO.OTROS`, que no es un servicio requerido). Es decir, si
   el inspector selecciona `LIMPIEZA_PISCINA` o `TRABAJOS_ELECTRICOS`, no hay campo para explicar
   "por qué" — pero el webhook de ejemplo pide `motivacion` en **cada** servicio ("Agua turbia,
   presencia de algas", "Acumulación de polvo tras desalojo").
   Hay un campo `motivacion` de nivel de levantamiento completo (`LevantamientoRequest.motivacion`),
   pero según la documentación es específico para justificar `inspeccion_tecnica_req`, no para
   servicios requeridos — reutilizarlo sería confuso y perdería la relación 1-a-1 con cada
   servicio si el inspector marca varios.
   → **Hay que decidir:** ¿habilitamos `permite_descripcion = TRUE` para todas las opciones de
   `LIMPIEZA`, `CERRAJERIA_MATERIAL` y `REPARACION` (migración simple) y usamos
   `SeleccionOpcion.descripcion` como el `motivacion` del webhook? Esto también cambiaría el
   formulario que ve el inspector (le pediría texto libre en más casos). Es la opción más simple
   y coherente con lo que ya existe.

2. **`tipo_servicio` no calza 1:1 con nuestro `tipo_catalogo`.** El ejemplo que te pasaron usa
   `"tipo_servicio": "LIMPIEZA"` para las tres filas, incluyendo "Retiro de Enseres" — que en
   nuestro catálogo es un `codigo` (`RETIRO_ENSERES`) dentro del grupo `LIMPIEZA`, consistente. Pero
   si un inspector selecciona algo de `CERRAJERIA_MATERIAL` o `REPARACION`, hay que confirmar con el
   otro desarrollador qué valor exacto de `tipo_servicio` espera para esos grupos (¿"CERRAJERIA"?
   ¿"REPARACION"? ¿usa su propio catálogo con otros nombres?). No asumir que nuestros nombres de
   `tipo_catalogo` internos son los que él espera sin confirmarlo.

3. **`fecha_inspeccion` pide un datetime con hora y zona ("2026-09-14T16:00:00Z")**, pero nosotros
   solo guardamos `fecha_levantamiento` como `date` (sin hora). Hay que decidir si se envía
   medianoche UTC de esa fecha (`f"{fecha_levantamiento}T00:00:00Z"`) o si se le pregunta al otro
   equipo si acepta solo fecha. Enviar una hora inventada (como medianoche) puede ser engañoso si
   ellos la muestran al usuario final.

4. **`latitud_inspeccion`/`longitud_inspeccion` como floats separados**, pero nosotros guardamos
   `coordenadas` como un solo string `"lat,lon"` sin validar formato ni rango en el request actual.
   Hay que parsear y separar con cuidado (¿qué se envía si `coordenadas` es `None` o tiene un
   formato inesperado? ¿se omite el webhook, se envían `null`, o se bloquea la finalización?).

5. **`numero_inspeccion` y `id_bien_inventario` no vienen en el resultado actual de
   `finalizar_levantamiento`.** Hoy
   [`LevantamientoFinalizeResult`](app/infrastructure/database/inspeccion_repository.py#L14-L18)
   solo trae `estado`, `id_levantamiento` y `respuesta_previa`. Va a haber que ampliar el `SELECT
   ... FOR UPDATE` que ya se hace sobre `inspecciones.inspeccion` (línea ~568) para traer también
   `numero_inspeccion` e `id_bien_inventario`, y devolverlos en el resultado.

6. **No hay que llamar al webhook dentro de la transacción de `finalizar_levantamiento`.** Esa
   transacción bloquea la fila de la inspección con `FOR UPDATE` mientras dura. Si el webhook HTTP
   está lento o el otro microservicio está caído, no queremos tener esa fila bloqueada esperando
   una respuesta externa. El callback debe hacerse en `InspeccionService`, **después** de que el
   repositorio confirme el commit, y solo cuando `resultado.estado == "creado"` (nunca en
   `"repetido"`, para no reenviar el webhook en reintentos idénticos del inspector — el mecanismo
   de idempotencia por `id_operacion` que ya existe nos da esto gratis).

7. **¿Qué pasa si el webhook falla o el otro servicio no responde?** Hoy no hay tabla de outbox ni
   reintentos. Si se implementa como llamada síncrona "best effort" (loguear el error y no
   fallar la finalización), el inspector no se entera si el otro servicio nunca se enteró del
   requerimiento — puede perderse silenciosamente. Alternativas, de menor a mayor esfuerzo:
   - **(a) Best-effort con log de error** (más simple, aceptable si el otro servicio es
     tolerante a estar sin este dato hasta que alguien lo note).
   - **(b) Guardar el intento en una tabla local (`levantamiento_webhook_intento` o similar) con
     estado `pendiente/enviado/fallido`**, y un job de reintento aparte (encaja bien con que ya
     mencionaste que esto migrará a un proceso batch de AWS más adelante).
   - **(c) No enviar nada nuevo — dejar que sea el futuro proceso de AWS Batch el que lea
     `servicios_requeridos` ya persistidos y llame al webhook por su cuenta**, sin tocar el
     endpoint de levantamiento en absoluto. Esto evita programar dos veces la misma
     integración (ahora acoplada al endpoint directo, y luego al batch).
   → Esto también es una decisión de producto/arquitectura que conviene confirmar contigo antes
   de programar el resto.

8. **No hay URL de este servicio en `settings.py`/`.env.example` todavía.** La URL que probaste
   (`161.97.86.251:8002`) es una IP:puerto fija de prueba — debe salir por variable de entorno
   (ej. `ORDENES_SERVICIO_WEBHOOK_URL`), nunca hardcodeada, siguiendo el mismo patrón que
   `AZURE_TENANT_ID`, etc. en [`settings.py`](app/infrastructure/config/settings.py).

## 4. Propuesta de implementación (una vez resueltos los puntos de la sección 3)

1. **Config** (`app/infrastructure/config/settings.py` + `.env.example`):
   - `ordenes_servicio_webhook_url: str = ""`
   - `ordenes_servicio_webhook_timeout: float = 10.0`
   - Si se opta por best-effort (3.7a), no hace falta flag de encendido/apagado: si la URL está
     vacía, el cliente simplemente no llama (igual que otros clientes opcionales del proyecto).

2. **Cliente HTTP** nuevo, ej. `app/infrastructure/clients/ordenes_servicio_client.py`, siguiendo
   el mismo patrón que [`AzureAdClient`](app/infrastructure/clients/azure_ad_client.py) (recibe
   `Settings`, usa `httpx.AsyncClient`, inyectable en tests, no lanza si falla — solo si se decide
   lo contrario en 3.7).

3. **Repositorio** (`inspeccion_repository.py`): ampliar el `SELECT ... FOR UPDATE` de
   `finalizar_levantamiento` para traer `numero_inspeccion` e `id_bien_inventario`, y agregarlos a
   `LevantamientoFinalizeResult`.

4. **Servicio** (`inspeccion_service.py::finalizar_levantamiento`): tras el `if resultado.estado
   == "repetido": ...` y antes del `return` final de éxito, si `body.servicios_requeridos` no está
   vacío, construir el payload y llamar al cliente. Mapear:
   - `inspeccion_id` ← `id_inspeccion`
   - `numero_inspeccion` ← `resultado.numero_inspeccion`
   - `id_bien_inventario` ← `resultado.id_bien_inventario`
   - `fecha_inspeccion` ← `body.fecha_levantamiento` (formateada según lo que se acuerde en 3.3)
   - `latitud_inspeccion` / `longitud_inspeccion` ← parseadas de `body.coordenadas`
   - `servicios_requeridos[]` ← por cada `SeleccionOpcion` en `body.servicios_requeridos`, resuelto
     contra el catálogo ya cargado (`opciones`) para obtener `tipo_catalogo` (→ `tipo_servicio`) y
     `nombre` (→ `subcategoria`), más `descripcion` (→ `motivacion`, si 3.1 se resuelve así).

5. **Tests**: unitarios del cliente (mock de `httpx.AsyncClient`), del mapeo de payload en el
   servicio, y confirmar que una finalización `"repetido"` **no** vuelve a llamar al webhook.

## 5. Qué necesito que confirmes antes de programar

- Punto 3.1: ¿habilitamos `descripcion` libre para todas las opciones de servicios requeridos?
- Punto 3.2: nombres exactos de `tipo_servicio` que espera el otro microservicio para
  `CERRAJERIA_MATERIAL` y `REPARACION`.
- Punto 3.3: ¿acepta solo fecha o de verdad necesita hora/zona horaria real?
- Punto 3.7: ¿best-effort con log, tabla de reintentos, o dejar esto completamente al futuro job
  de AWS Batch?
