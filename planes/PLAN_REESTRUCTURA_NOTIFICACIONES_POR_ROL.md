# Plan de reestructura — notificaciones por rol con lectura por usuario

> **Estado:** implementado. Lo que sigue documenta el diseño original y su razonamiento; las
> notas "Actualización tras implementar" marcan dónde la implementación final terminó distinta
> de lo propuesto acá — en particular, §5.1 (decodificar sin validar el JWT).

## 1. Objetivo

Eliminar la dependencia de Microsoft Entra ID al **crear** una notificación dirigida a un rol.
Hoy, `POST /inspeccion/notificaciones` con `rol` resuelve en vivo los miembros del grupo de Entra ID
correspondiente y crea una fila por cada email resuelto. La propuesta es:

1. Crear la notificación **una sola vez**, dirigida al rol como concepto (`rol_destino`), sin
   resolver usuarios ni llamar a Microsoft Graph.
2. Cuando un usuario se autentica, extraer su `email` y su `rol` del token (JWT) en vez de
   depender de una fila ya materializada para ese email.
3. Determinar si una notificación está "leída" para ese usuario mediante un `LEFT JOIN` contra
   una tabla nueva de lecturas, en vez de mediante una columna `estado` en la propia fila de
   notificación (que hoy solo puede pertenecer a un email).

## 2. Diagnóstico del diseño actual

Referencia: `app/application/notificacion_service.py`,
`app/infrastructure/database/notificacion_repository.py`,
`app/presentation/api/routers/notificaciones.py`,
`migrations/versions/20260905_0027_create_notificacion_table.py`.

- La tabla `inspecciones.notificacion` tiene **una fila por destinatario resuelto**:
  `email_destinatario VARCHAR(255) NOT NULL` es parte del núcleo del modelo. `estado` (`NO_LEIDA` /
  `VISTA` / `SILENCIADA` / `CERRADA`) vive en esa misma fila — es decir, el estado de lectura es
  una propiedad de la fila, no de la relación (usuario, notificación).
- Al crear con `rol`, el router (`crear_notificacion`, líneas 72-104 de
  `routers/notificaciones.py`) llama a `AzureAdClient.get_group_members(grupo)` de forma
  **síncrona, dentro del request**, y arma un `INSERT` masivo (`insert_many`) con una fila por
  email resuelto. Esto acopla la creación de la notificación a la disponibilidad de Microsoft
  Graph (`AzureAdError` → `502`) y a la membresía del grupo **en el instante de creación**.
- Consecuencia directa de fijar la membresía en el instante de creación: un usuario que se une al
  rol **después** de creada la notificación nunca la ve (no se le insertó fila); uno que sale del
  rol sigue viéndola indefinidamente (su fila ya existe y nadie la borra).
- `GET /inspeccion/notificaciones` filtra `WHERE email_destinatario = $1` — funciona porque cada fila
  ya "pertenece" a un email.
- `PATCH /{id}/{accion}` verifica dueño con `row["email_destinatario"] != usuario` — el concepto de
  "dueño" solo tiene sentido porque hoy cada fila es 1:1 con un email.
- La autenticación actual (`get_current_user_email`,
  `app/presentation/api/dependencies/inspecciones.py:36-47`) **no decodifica ningún JWT**: lee el
  header `X-User-Email` tal cual, confiando en que algo upstream (API Gateway) ya lo validó. No
  existe hoy ningún campo de rol de usuario disponible en la capa de autenticación del
  microservicio — no hay `get_current_user_role` ni equivalente.
- No hay ninguna librería de validación de JWT en las dependencias del proyecto (`pyjwt`,
  `python-jose`, `authlib`, etc. no aparecen en `pyproject.toml`). La única dependencia relacionada
  con identidad es `msal`, y se usa para que el propio microservicio adquiera un token de
  aplicación y llame a Microsoft Graph (`AzureAdClient`, flujo *client credentials*) — es lo
  opuesto a validar un token de usuario entrante.

## 3. Propuesta de modelo de datos

### 3.1 `inspecciones.notificacion` (rediseñada)

```text
id_notificacion     UUID PRIMARY KEY DEFAULT gen_random_uuid()
rol_destino         VARCHAR(50)              NULL   -- p. ej. INSPECTOR, OFICIAL_BIENES_ADQUIRIDOS
email_destinatario  VARCHAR(255)             NULL   -- para notificaciones 1:1, se conserva
tipo_notificacion   VARCHAR(50)  NOT NULL
titulo              VARCHAR(255) NOT NULL
mensaje             VARCHAR(1000) NOT NULL
referencia_tipo     VARCHAR(50)
referencia_id       UUID
estado_notificacion VARCHAR(20)  NOT NULL DEFAULT 'ACTIVA'
                     CHECK (estado_notificacion IN ('ACTIVA', 'CERRADA'))
fecha_creacion      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
fecha_cerrada       TIMESTAMPTZ
creado_por          VARCHAR(150)

CHECK (
  (rol_destino IS NOT NULL AND email_destinatario IS NULL)
  OR
  (rol_destino IS NULL AND email_destinatario IS NOT NULL)
)
```

Cambios respecto a hoy:

- `email_destinatario` pasa de `NOT NULL` a nullable; se agrega `rol_destino`, con un `CHECK` que
  exige exactamente uno de los dos (mismo principio que ya aplica `CrearNotificacionRequest` a
  nivel de payload, ahora reflejado también en la tabla).
- `estado` deja de representar "leída/vista/silenciada" (eso se mueve a la tabla nueva) y pasa a
  representar solo el **ciclo de vida de la notificación como concepto**: `ACTIVA` o `CERRADA`.
  `CERRADA` sigue siendo lo que hoy hace `close_previous` — cuando se crea una notificación nueva
  para la misma `referencia_tipo` + `referencia_id` + `tipo_notificacion`, la anterior se cierra
  para todos (ya no es relevante para nadie), independientemente de quién la haya leído o no.
- Se elimina `fecha_vista` / `fecha_silenciada` de esta tabla — ahora son por usuario, no por
  notificación.

### 3.2 `inspecciones.notificacion_lectura` (nueva)

```text
id_notificacion  UUID          NOT NULL REFERENCES inspecciones.notificacion(id_notificacion)
                                ON DELETE CASCADE
email_lector     VARCHAR(255)  NOT NULL
estado_lector    VARCHAR(20)   NOT NULL DEFAULT 'VISTA'
                  CHECK (estado_lector IN ('VISTA', 'SILENCIADA'))
fecha_vista      TIMESTAMPTZ
fecha_silenciada TIMESTAMPTZ

PRIMARY KEY (id_notificacion, email_lector)
```

> **Punto a confirmar (ver §5.1):** en la descripción original se pidió que la tabla de lecturas
> "tenga como primary key el email del usuario". Tomado literalmente, una PK de una sola columna
> `email` solo permitiría **una fila por usuario en total**, no una fila por cada notificación que
> ese usuario ya leyó — y el propio flujo descrito ("buscar si el usuario tiene un registro para
> esa notificación") necesita distinguir notificación por notificación. La PK compuesta
> `(id_notificacion, email_lector)` es la que hace posible exactamente el comportamiento pedido:
> "si no tiene un registro en esa tabla [para esa notificación], no la ha leído".

Semántica: **la ausencia de fila = no leída** (comportamiento por defecto, sin necesidad de
insertar nada al crear la notificación ni al agregar miembros al rol). La presencia de fila con
`estado_lector = 'VISTA'` o `'SILENCIADA'` es lo que el usuario marcó explícitamente sobre esa
notificación puntual, sin afectar a los demás destinatarios del mismo rol.

## 4. Flujos reescritos

### 4.1 Crear (`POST /inspeccion/notificaciones`)

- Ya no llama a `AzureAdClient` ni a Microsoft Graph en absoluto para el caso `rol`.
- `INSERT` de **una sola fila**: `rol_destino = body.rol` o `email_destinatario =
  body.email_destinatario`, según el caso — igual que hoy, exactamente uno de los dos.
- `close_previous` (cierre de notificaciones anteriores sobre la misma referencia) pasa a
  filtrar por `rol_destino = body.rol OR email_destinatario = body.email_destinatario` en vez de
  por una lista de emails resueltos, y marca `estado_notificacion = 'CERRADA'` en la tabla
  `notificacion` (no toca `notificacion_lectura`).
- `CrearNotificacionResponse` deja de tener sentido con `total_creadas` / `ids_creados` como
  arreglo (siempre sería 1); se simplifica a devolver el `id_notificacion` único creado. Esto es
  un **cambio de contrato** (ver §5.2).

### 4.2 Listar (`GET /inspeccion/notificaciones`)

Requiere que la capa de autenticación entregue **email y rol** del usuario (ver §5.1). Con eso:

```sql
SELECT n.id_notificacion, n.tipo_notificacion, n.titulo, n.mensaje,
       n.referencia_tipo, n.referencia_id, n.fecha_creacion,
       COALESCE(l.estado_lector, 'NO_LEIDA') AS estado,
       l.fecha_vista
FROM inspecciones.notificacion n
LEFT JOIN inspecciones.notificacion_lectura l
       ON l.id_notificacion = n.id_notificacion
      AND l.email_lector = $1              -- email del token
WHERE n.estado_notificacion = 'ACTIVA'
  AND (n.email_destinatario = $1 OR n.rol_destino = ANY($2::varchar[]))  -- rol(es) del token
  AND ($3::varchar IS NULL OR COALESCE(l.estado_lector, 'NO_LEIDA') = $3)
ORDER BY n.fecha_creacion DESC
```

`total_no_leidas` pasa de `COUNT(*) WHERE estado = 'NO_LEIDA'` a
`COUNT(*) WHERE l.id_notificacion IS NULL` sobre el mismo `LEFT JOIN` — "no tiene fila en
`notificacion_lectura`" es exactamente la definición de no leída pedida.

`rol_destino = ANY($2::varchar[])` (en vez de `= $2`) porque el token puede traer más de un rol
por usuario (ver §5.4).

### 4.3 Marcar como vista/silenciada (`PATCH /{id}/{accion}`)

- Ya no existe "dueño único" de la fila (una notificación por rol tiene N destinatarios
  potenciales). El chequeo de pertenencia cambia de
  `row.email_destinatario != usuario → 403` a: la notificación aplica al usuario si
  `n.email_destinatario = email` **o** `n.rol_destino` está entre los roles del token; si no
  aplica → `403`.
- La acción deja de ser un `UPDATE` sobre `notificacion` y pasa a ser un `UPSERT` sobre
  `notificacion_lectura`:
  `INSERT INTO notificacion_lectura (...) VALUES (...) ON CONFLICT (id_notificacion, email_lector)
  DO UPDATE SET estado_lector = EXCLUDED.estado_lector, fecha_vista/fecha_silenciada = NOW()`.
- `NotificacionNoActivaError` (hoy: "ya estaba silenciada o cerrada") deja de aplicar sobre
  `SILENCIADA` por usuario (cada usuario puede pasar de `VISTA` a `SILENCIADA` para sí mismo sin
  restricción) y se conserva solo para el caso `estado_notificacion = 'CERRADA'` (la notificación
  ya no es válida para nadie).

### 4.4 Notificación a un email puntual — sí está contemplado, y es el mismo flujo sepa o no el rol

Pregunta concreta: si mañana se quiere notificar a **una persona específica** (no a todo un rol),
¿cambia algo si quien crea la notificación conoce el rol de esa persona, frente a si solo tiene el
email? **No cambia nada — es el mismo flujo en los dos casos**, y ya está cubierto por el diseño de
§3.1/§3.2 sin necesidad de ningún campo ni caso especial adicional. La razón es estructural: el
mecanismo de lectura (`notificacion_lectura`) siempre hace *match* por `email_lector`, nunca por
rol — el rol solo participa en decidir el `WHERE` de `notificacion` para las difusiones por rol
(§4.2), pero una notificación dirigida a un email ya tiene un único destinatario posible sin que el
rol tenga que intervenir en absoluto.

**Caso A — se sabe el rol y el email** (p. ej. "sé que es del rol `INSPECTOR` y tengo su email"):

1. `POST /notificaciones` con `email_destinatario = "persona@dominio.com"` — igual que hoy exige la
   validación de exactamente un destinatario, **se sigue usando `email_destinatario`, nunca
   `rol_destino`**, aunque se conozca el rol. Conocer el rol no aporta nada a la creación: no se
   usa para enrutar (ya se tiene el email exacto) y, a diferencia del diseño actual, tampoco se
   puede usar para *validar* que ese email realmente pertenece a ese rol — ver el matiz de
   confianza más abajo.
2. Se inserta **una fila** en `notificacion` con `rol_destino = NULL`.
3. Cuando esa persona inicia sesión, su token trae su `preferred_username` (email) y su(s)
   `roles` — no importa cuál(es) sea(n) esos roles, porque el `WHERE` de `GET /notificaciones`
   matchea esta fila por la rama `n.email_destinatario = $1` (su propio email), no por
   `rol_destino`.
4. El `LEFT JOIN` contra `notificacion_lectura` funciona exactamente igual que en una notificación
   de rol: si no hay fila `(id_notificacion, su_email)`, aparece como `NO_LEIDA` y cuenta en
   `total_no_leidas`; al hacer `PATCH .../vista`, el chequeo de pertenencia (§4.3) valida
   `n.email_destinatario = email` → aplica → se hace el `UPSERT` en `notificacion_lectura` como
   cualquier otra.

**Caso B — solo se tiene el email, no se sabe el rol:** exactamente el mismo flujo de arriba,
porque `rol_destino` nunca fue necesario para este camino. La ausencia de dato de rol no bloquea
nada — simplemente no se llena esa columna (queda `NULL`, como en el Caso A).

En resumen: **saber o no el rol es irrelevante para este flujo.** La única decisión que importa al
crear es "¿esto es para una persona puntual o para todos los que tengan tal rol?" — si es lo
primero, siempre se usa `email_destinatario` y el resto (lectura, conteo de no leídas, marcar
vista/silenciada) es idéntico a lo ya descrito en §3-§4 sin ningún ajuste adicional.

**Matiz de confianza que sí vale la pena dejar explícito:** el diseño actual (antes de esta
reestructura) llama a Microsoft Graph para *resolver* los miembros de un rol, lo cual de paso
garantiza que cada email al que se le crea una fila efectivamente pertenece a alguien con ese rol
en Entra ID. Al eliminar esa llamada, `POST /notificaciones` con `email_destinatario` deja de tener
cómo verificar que el email indicado exista o tenga el rol que quien lo crea cree que tiene —
pasa a ser responsabilidad de quien llama al endpoint escribir el email correcto (debe ser
exactamente el `preferred_username`/UPN que traerá el token de esa persona, igual que ya aplica hoy
para `email_inspector` frente a `GET /inspectores`). No es un bloqueante — es el mismo nivel de
confianza que ya existía para el camino `email_destinatario` de hoy — pero es una pérdida real de
validación automática que sí existía para el camino `rol` (porque antes *todo* pasaba por Graph).
Si en el futuro se necesita esa garantía de nuevo, sería una llamada a Graph puntual y explícita en
el momento de crear una notificación individual — no algo que este plan proponga ahora mismo.

## 5. Puntos abiertos y posibles bloqueantes

### 5.1 Resuelto: el Gateway reenvía el JWT crudo; este microservicio debe decodificarlo y validarlo él mismo

Se confirmó con el dueño de este plan que el API Gateway **no** decodifica el token ni inyecta
headers derivados: reenvía tal cual el header `Authorization: Bearer <JWT>` que emite Microsoft
Entra ID (Azure AD v2.0). Eso descarta la opción 1 que este documento dejaba abierta ("el Gateway
inyecta `X-User-Roles`") y confirma la opción 2: **`ms_inspecciones` tiene que validar la firma y
leer los claims del token él mismo**, porque nada aguas arriba lo hace por él.

Como evidencia se compartió un JWT real de este mismo tenant de Entra ID (emitido para otra API del
ecosistema, `ms-bien`, pero con exactamente la forma que va a recibir este microservicio), cuyo
payload decodificado trae:

```json
{
  "aud": "e93a26a9-7072-42e4-a7ef-e44c807c7608",
  "iss": "https://login.microsoftonline.com/46d6f84d-62af-4baa-82b1-ad4885cfc5f1/v2.0",
  "exp": 1788910792,
  "name": "David Sarria",
  "preferred_username": "davidsoporte2@caja.realidad5.com",
  "roles": ["DEV_BIEN_APROBADOR2"],
  "ver": "2.0"
}
```

Lecturas clave de este ejemplo para el diseño:

- **El rol no viene de un grupo de directorio, viene de un claim `roles` del propio token** — es
  el mecanismo de *App Roles* de Entra ID (roles definidos en el App Registration y asignados a
  usuarios/grupos desde "Enterprise applications"), completamente distinto a
  `AzureAdClient.get_group_members("Inspectores")`, que hoy consulta membresía de un **grupo de
  directorio** vía Microsoft Graph. Confirma que el patrón "roles como claim firmado en el token"
  ya está operando en este mismo tenant para otro microservicio hermano — no es una idea nueva, es
  alinear `ms_inspecciones` con algo que ya funciona así al lado.
- **`roles` es un arreglo**, no un escalar (`["DEV_BIEN_APROBADOR2"]`) — confirma como real la
  duda que §5.4 dejaba abierta: un usuario puede tener más de un rol asignado, y el filtro de
  `GET /notificaciones` / el chequeo de pertenencia de `PATCH` deben comparar contra **todos** los
  roles del token (`rol_destino = ANY(...)`), tal como ya quedó modelado en §4.2/§4.3.
- **No hay un claim llamado `email`** — el identificador de correo viene en `preferred_username`
  (UPN). El código que decodifique el token debe leer `preferred_username`, no buscar un campo
  `email` que Entra ID no está emitiendo aquí. Es consistente con lo que ya hace
  `GET /inspeccion/inspectores` al usar `userPrincipalName` como respaldo de `mail`.
- **`aud` y `roles` de este token específico pertenecen al App Registration de `ms-bien`**
  (`DEV_BIEN_APROBADOR2` sigue la convención de nombres de esa app, no la de
  `RolNotificacion`/`GRUPO_AD_POR_ROL` de este repo). Es decir: sirve para confirmar la **forma**
  del token (claims, algoritmo, tenant), pero **no** los valores concretos que `ms_inspecciones`
  debe esperar — `ms_inspecciones` necesita su propio `aud` (el *Application ID* de su propio App
  Registration, o el que se haya configurado como *audience* expuesto) y sus propios App Roles
  (`INSPECTOR`, `OFICIAL_BIENES_ADQUIRIDOS`, ya usados hoy como valores de `RolNotificacion`)
  dados de alta en Entra ID antes de poder validar nada en producción. Falta confirmar con quien
  administra Entra ID si `ms_inspecciones` ya tiene su propio App Registration con esos roles
  definidos, o si hay que crearlo/pedirlo.

**Qué implica esto en el código, a alto nivel** (sin implementarlo todavía):

- Nueva dependencia de autenticación que reemplaza/extiende a `get_current_user_email`: recibe
  `Authorization: Bearer <token>`, valida firma (RS256) contra las claves públicas (JWKS) del
  tenant (`https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys`, descubribles desde el
  propio `iss`), valida `exp`/`nbf`, valida `aud` contra el *Application ID* propio de
  `ms_inspecciones`, y devuelve `{email: preferred_username, roles: roles}`. Un token expirado,
  mal firmado, o con `aud` incorrecto debe responder `401`.
- Requiere una librería de validación de JWT que hoy no está en el proyecto (`pyjwt[crypto]` o
  `python-jose[cryptography]`; `msal`, la única dependencia de identidad actual, sirve para que
  este servicio **adquiera** tokens propios contra Graph, no para **validar** tokens ajenos —  son
  usos opuestos).
- Requiere cachear el JWKS (no pedirlo a Entra ID en cada request) con invalidación por `kid`
  desconocido, para no convertir cada login en una llamada de red — a diferencia de la resolución
  de miembros de grupo que se elimina con este plan, aquí la llamada de red solo ocurre en
  rotación de claves, no por notificación ni por request de usuario.
- Necesita configuración nueva en `Settings`: el `azure_tenant_id` ya existe y es reutilizable
  para construir el *issuer*/JWKS; falta un valor de *audience* esperado propio de
  `ms_inspecciones` (hoy `azure_backend_client_id` es el *client id* que el servicio usa para
  llamarse a sí mismo hacia Graph — hay que confirmar si es el mismo Application ID que debe
  aparecer como `aud` en los tokens entrantes, o si son dos registros de aplicación distintos).
- `X-User-Email` como mecanismo de "autenticación" queda para desarrollo local únicamente (ya es
  así hoy detrás de `settings.is_local`); en el resto de ambientes la fuente de verdad pasa a ser
  el token decodificado.

> **Actualización tras implementar (1):** se decidió que el módulo de notificaciones **no** tenga
> ningún atajo por `IS_LOCAL` — a diferencia de `X-User-Email` en el resto de la API, aquí siempre
> se exige un `Authorization: Bearer`, incluso en desarrollo local. La razón es que el rol solo
> existe dentro de un token real; un header de rol puesto a mano por el propio desarrollador no
> prueba nada del mecanismo real.

> **Actualización tras implementar (2) — decisión final, reemplaza el resto de esta sección:**
> se decidió explícitamente **no validar** el token — ni firma, ni `exp`, ni `aud`, ni `iss`. Todo
> lo que sigue en esta sección (JWKS, `PyJWKClient`, verificación RS256, `AZURE_API_AUDIENCE`)
> describe el diseño original y **no** es lo que quedó implementado. La justificación explícita
> del dueño de este plan: la seguridad ya la resuelve el API Gateway antes de que la solicitud
> llegue a este microservicio; revalidar acá es responsabilidad duplicada e innecesaria. En la
> implementación final, `app/infrastructure/clients/entra_token_decoder.py` hace solo
> `jwt.decode(token, options={"verify_signature": False})` — sin llamadas de red, sin JWKS, sin
> caché, sin `AZURE_API_AUDIENCE` (se eliminó de `Settings`). Un token vencido o con firma
> incorrecta se acepta igual; el único rechazo (`401`) es un token que no tiene forma de JWT o que
> no trae `preferred_username`.
>
> Vale dejar explícito el trade-off, no como objeción sino como algo que el equipo debe tener
> presente: cualquier corrección que llegue con un `preferred_username`/`roles` bien formados —
> vencida, de otra aplicación del mismo tenant, o directamente fabricada por alguien que sepa
> construir un JWT sin firmar — es aceptada por `ms_inspecciones` si logra llegarle directamente
> sin pasar por el Gateway. El diseño asume que la única vía de entrada real es a través del
> Gateway (por red, por configuración de infraestructura) y que nada más puede alcanzar este
> microservicio directamente — es una decisión de arquitectura de despliegue, no de este código.

Con esto, el bloqueante que dejaba abierto este documento queda resuelto: **sí, hay que decodificar
el JWT dentro de `ms_inspecciones`** — pero, a diferencia de lo que proponía originalmente esta
sección, sin validarlo.

### 5.2 Cambio de contrato en `POST /inspeccion/notificaciones`

Hoy la respuesta es `{"total_creadas": N, "ids_creados": [...]}` (uno por email resuelto). Con
creación de una sola fila por rol, `total_creadas` sería siempre `0` o `1` y `ids_creados` un
arreglo de a lo sumo un elemento — un cambio de forma, no solo de valores. Si algún cliente ya
integrado depende de recibir varios IDs (por ejemplo, para enlazar cada notificación creada con un
destinatario concreto), ese consumidor se rompe. Confirmé en la sesión anterior que **nada dentro
de este mismo backend llama hoy a este endpoint automáticamente** (no hay disparadores de negocio
implementados todavía — ver hallazgo de la conversación previa), así que el radio de impacto real
depende únicamente de si el frontend ya construyó algo sobre esa respuesta.

### 5.3 Qué significa "silenciar" cuando la notificación es de un rol compartido

El diseño de §3.2/§4.3 asume que silenciar es **por usuario**: cada quien puede ocultar su propia
copia de una notificación de rol sin afectar a sus compañeros de rol. Es la lectura más natural de
lo pedido, pero vale confirmarla explícitamente porque es una decisión de producto, no solo
técnica — la alternativa (silenciar de forma global para todo el rol) cambiaría §3.1/§3.2
sustancialmente (volvería a acoplar "silenciada" a la fila de `notificacion` en vez de a
`notificacion_lectura`).

### 5.4 Resuelto: un usuario puede tener más de un rol

Confirmado con el token real de §5.1: `roles` es un arreglo (`["DEV_BIEN_APROBADOR2"]`), no un
escalar. El filtro de `GET /notificaciones` y el chequeo de pertenencia de `PATCH` deben comparar
contra **todos** los roles del token (`rol_destino = ANY(...)`), tal como ya quedó modelado en
§4.2/§4.3 — no como una posibilidad a confirmar, sino como un requisito.

### 5.5 Cambio de semántica: retroactividad ante cambio de rol

Hoy, si un usuario cambia de rol, su bandeja no cambia retroactivamente (las filas ya estaban
fijadas a su email desde que se crearon). Con el modelo nuevo, el filtro se evalúa **en cada
`GET`, contra el rol vigente en el token en ese momento** — si el usuario cambia de rol, en la
siguiente consulta ve el conjunto de notificaciones del rol nuevo y deja de ver las del rol
anterior, incluidas notificaciones antiguas que nunca marcó como leídas. Es probablemente el
comportamiento deseado (evita el problema actual de "se unió tarde y no la ve"), pero es un cambio
de semántica frente a hoy y conviene confirmarlo explícitamente como aceptado.

### 5.6 Migración del histórico

Las filas existentes en `inspecciones.notificacion` ya tienen `email_destinatario` poblado y
`estado` con valores de las cuatro categorías actuales. Conviven sin conflicto con el modelo nuevo
si se tratan como notificaciones "directas a email" (que siguen existiendo en el diseño
propuesto): `estado_notificacion` puede derivarse como `CERRADA` si `estado` era `CERRADA`,
`ACTIVA` en cualquier otro caso; y una fila de `notificacion_lectura` puede backfillearse por cada
notificación histórica que ya tuviera `fecha_vista` o `fecha_silenciada` no nulas, usando el propio
`email_destinatario` como `email_lector`. Esto es una migración de datos, no solo de esquema — hay
que decidir si vale la pena conservar el histórico así de exacto o si basta con partir "limpio"
desde la fecha del corte (dado que, según lo confirmado antes, hoy no hay ningún volumen real
generado por triggers automáticos).

### 5.7 Nota de rendimiento: filtro `OR` entre dos columnas distintas

`WHERE n.email_destinatario = $1 OR n.rol_destino = ANY($2)` no es tan sargable como dos
condiciones sobre la misma columna — Postgres puede resolverlo con un `BitmapOr` de dos índices
(uno por columna) si el volumen lo justifica, o puede convenir modelar la consulta como
`UNION ALL` de "las mías por email" + "las de mi rol". No es bloqueante, pero es una decisión de
índices a tomar en la migración (`idx_notificacion_rol_destino`,
`idx_notificacion_email_destinatario`, ambos filtrando `estado_notificacion = 'ACTIVA'`).

## 6. Impacto estimado en el código existente (sin tocarlo todavía)

Solo como mapa de alcance para cuando se decida implementar — nada de esto se modificó al escribir
este plan:

| Archivo | Qué cambiaría |
|---|---|
| `migrations/versions/20260905_0027_create_notificacion_table.py` | Nueva migración adicional: altera `notificacion` (nullable `email_destinatario`, agrega `rol_destino`, colapsa `estado` en `estado_notificacion`), crea `notificacion_lectura` |
| `app/infrastructure/database/notificacion_repository.py` | Reescribir `list_for_user`, `count_no_leidas`, `update_estado` (pasa a upsert sobre la tabla nueva), `close_previous`, `insert_many` (pasa a insertar 1 fila) |
| `app/application/notificacion_service.py` | `listar`/`marcar`/`crear` ya no dependen de `AzureAdClient`; `marcar` cambia el chequeo de pertenencia |
| `app/presentation/api/routers/notificaciones.py` | `crear_notificacion` deja de inyectar/usar `AzureAdClient`; los tres endpoints necesitan el rol del usuario, no solo el email |
| `app/presentation/api/dependencies/inspecciones.py` | Nueva dependencia `get_notificacion_user` que decodifica (sin validar) el `Authorization: Bearer` y devuelve `{email: preferred_username, roles}` — no reemplaza a `get_current_user_email`, solo la usan los tres endpoints de notificaciones (decisión final, ver actualización en §5.1) |
| `pyproject.toml` | Nueva dependencia `pyjwt` (sin el extra `[crypto]`: no se verifica firma, así que no hace falta backend de RSA) |
| `app/presentation/api/schemas/notificaciones.py` | `CrearNotificacionRequest`/`Response`, `NotificacionItem` ajustan campos |
| `tests/application/test_notificacion_service.py`, `tests/infrastructure/test_notificacion_repository.py`, `tests/api/test_notificaciones.py` | Las 17 pruebas actuales asumen fan-out por email y ownership 1:1; prácticamente todas requieren reescritura |
| `API_REFERENCE_MS_INSPECCIONES.md`, `BACKEND_MS_INSPECCIONES.md` | Sección de notificaciones a actualizar con el nuevo contrato |

## 7. Orden sugerido si se aprueba

1. ~~Confirmar el *Application ID* (`aud`) propio de `ms_inspecciones` en Entra ID~~ — ya no
   aplica: la decisión final (§5.1, actualización 2) fue no validar `aud` en absoluto.
2. Construir `get_notificacion_user`: decodificar (sin verificar firma/`exp`/`aud`/`iss`) el
   `Authorization: Bearer` y extraer `preferred_username`/`roles`.
3. Confirmar §5.3 (silenciado por usuario vs. global).
4. Migración: alterar `notificacion` + crear `notificacion_lectura` + índices de §5.7.
5. Repositorio y servicio (con tests reescritos primero, dado el patrón TDD que ya sigue este
   repo).
6. Router + contrato (romper `CrearNotificacionResponse` de forma explícita, documentarlo).
7. Sincronizar `API_REFERENCE_MS_INSPECCIONES.md` / `BACKEND_MS_INSPECCIONES.md`.
8. Decidir §5.6 (qué hacer con el histórico) como parte de la migración, no después.

## 8. Conclusión

La idea central — notificar por rol sin fan-out, y resolver "leída" con un `LEFT JOIN` contra una
tabla de lecturas por usuario — es sólida y sí resuelve el problema real de acoplar la creación de
una notificación a una llamada síncrona a Microsoft Graph. El bloqueante que este documento dejaba
abierto sobre autenticación ya se resolvió: se confirmó que el API Gateway reenvía el
`Authorization: Bearer` crudo sin decodificarlo, así que `ms_inspecciones` va a tener que validar
el JWT y leer `roles`/`preferred_username` él mismo — no hay atajo vía un header ya resuelto por el
Gateway. Un token real de este mismo tenant de Entra ID (compartido en la conversación, ver §5.1)
confirma la forma exacta a esperar: `roles` como arreglo de App Roles firmado en el token, y el
correo en `preferred_username`, no en un claim `email`. Todo lo demás en este plan (modelo de dos
tablas, `LEFT JOIN`, `UPSERT` de lectura, `CHECK` de destinatario único) es viable sin sorpresas;
lo único que falta por confirmar antes de implementar es operativo — el *Application ID* propio de
`ms_inspecciones` y sus App Roles en Entra ID — no arquitectónico.
