# ms-inspecciones

Base del microservicio de inspecciones, preparada para ejecutarse con FastAPI y desplegarse
posteriormente en Docker/AWS Fargate. Esta primera iteración solo incluye endpoints operativos,
conectividad PostgreSQL/PostGIS y migraciones; no contiene lógica de negocio de inspecciones.

El stack utiliza Python 3.13, FastAPI, Uvicorn, Pydantic v2, pydantic-settings, asyncpg,
Alembic, uv, pytest, httpx y Ruff. La aplicación accede a PostGIS directamente con asyncpg;
SQLAlchemy existe únicamente como dependencia interna de Alembic, no como ORM de aplicación.

## Documentación

- [API Reference](docs/API_REFERENCE_MS_INSPECCIONES.md): referencia completa de endpoints,
  request/response y códigos de error del servicio.
- [Backend actual](docs/BACKEND_MS_INSPECCIONES.md): diseño y alcance del microservicio
  independiente `ms_inspecciones`.
- [Despliegue en EC2 con systemd](docs/DESPLIEGUE_EC2_SYSTEMD.md): despliegue manual desde una
  máquina Ubuntu local hacia EC2, sin contenedores.
- [Disparadores de notificación (HU5)](docs/DISPARADORES_NOTIFICACIONES_HU5.md): eventos que
  disparan notificaciones en el módulo de inspecciones v2.
- [Esquema de base de datos](docs/ESQUEMA_BASE_DATOS_ACTUAL.md): estado actual del schema
  `inspecciones` resultante de la cadena de migraciones Alembic.

## Requisitos

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 17 con PostGIS 3.5 (para ejecución sin contenedores)
- Docker y Docker Compose (para el flujo con contenedores)

## Instalación

```bash
uv sync
cp .env.example .env
```

`uv sync` crea el entorno virtual e instala dependencias normales y de desarrollo desde
`uv.lock`. El archivo `.env` está ignorado por Git y nunca debe incluirse en commits.

## Variables de entorno

| Variable | Uso |
| --- | --- |
| `APP_NAME` | Nombre del servicio incluido en respuestas y logs. |
| `ENVIRONMENT` | Entorno actual, por ejemplo `local`, `staging` o `production`. |
| `LOG_LEVEL` | Nivel mínimo de logging. |
| `DATABASE_HOST` / `DATABASE_PORT` | Dirección de PostgreSQL. |
| `DATABASE_NAME` | Base de datos compartida existente; para este servicio es `Caja`. |
| `DATABASE_USER` / `DATABASE_PASSWORD` | Credenciales de conexión. |
| `DATABASE_SCHEMA` | Schema propiedad del servicio; debe ser `inspecciones`. |
| `DATABASE_POOL_MIN_SIZE` / `DATABASE_POOL_MAX_SIZE` | Límites del pool asyncpg. |
| `DATABASE_CONNECT_TIMEOUT` | Timeout de conexión en segundos. |
| `ENABLE_DIRECT_LEVANTAMIENTO_ENDPOINT` | Habilita temporalmente `POST /{id_inspeccion}/levantamiento`; `false` por defecto. El catálogo `GET /levantamiento/catalogos` no depende de esta variable. |

La cadena de conexión se construye internamente. No se registra ni se devuelve en errores.

## Ejecución local sin Docker

Con PostgreSQL/PostGIS accesible según `.env`:

```bash
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

La API queda disponible en `http://localhost:8000`. Sus endpoints operativos son:

- `GET /v1/inspeccion/health`: confirma que FastAPI responde, sin consultar la base.
- `GET /v1/inspeccion/ready`: ejecuta `SELECT PostGIS_Version();` mediante el pool asyncpg y devuelve
  503 sin detalles sensibles si PostgreSQL o la extensión PostGIS no están disponibles.

## Consulta de inventario

El inventario se lee directamente desde `inspecciones.v_consulta_inventario`; la aplicación no
realiza llamadas HTTP a ms-bien ni contiene consultas a tablas `bien.*`. La vista normal se crea
mediante Alembic y refleja en tiempo real los cambios de las tablas fuente.

Las URL finales, incluido el prefijo global del servicio, son:

```text
GET /v1/inspeccion/coactivo/inventario/consulta
GET /v1/inspeccion/coactivo/inventario/consulta/filtro
GET /v1/inspeccion/gestion
```

Ejemplos:

```bash
curl --location \
  'http://localhost:8000/v1/inspeccion/coactivo/inventario/consulta?pagina=1&tamanio=15'

curl --location \
  'http://localhost:8000/v1/inspeccion/coactivo/inventario/consulta/filtro?pagina=1&tamanio=15&numero_finca=12345'

curl --location \
  'http://localhost:8000/v1/inspeccion/coactivo/inventario/consulta/filtro?pagina=1&tamanio=15&numero_finca=12345&todos=true'
```

El rol que ejecute la migración debe tener `USAGE` sobre `bien` y `SELECT` sobre las columnas
fuente utilizadas por la vista. El rol de ejecución necesita únicamente `USAGE` sobre
`inspecciones` y `SELECT` sobre `inspecciones.v_consulta_inventario`. Infraestructura debe
reemplazar los marcadores por los roles reales del ambiente:

```sql
GRANT USAGE ON SCHEMA bien TO <rol_migraciones>;
GRANT SELECT ON bien.bien_inventario, bien.bien, bien.deudor, bien.tipo_propiedad,
    bien.direccion, bien.corregimiento, bien.distrito, bien.provincia,
    bien.informacion_contable, bien.estatus_bien_inventario, bien.estado_inventario,
    bien.oficinista, bien.finca
TO <rol_migraciones>;

GRANT USAGE ON SCHEMA inspecciones TO <rol_runtime>;
GRANT SELECT ON inspecciones.v_consulta_inventario TO <rol_runtime>;
```

## Colección Postman

Importe `ms-inspecciones.postman_collection.json` en Postman para ejecutar los endpoints del
servicio. La colección utiliza `{{baseUrl}}`, cuyo valor predeterminado es
`http://localhost:8000`, y está organizada en carpetas para incorporar nuevos recursos a medida
que se implementen.

## Ejecución con Docker Compose

El compose usa PostgreSQL 17 con PostGIS 3.5 y credenciales exclusivas de desarrollo local.

### Primera vez (orden obligatorio)

```bash
# 1. Levantar PostGIS y esperar a que esté healthy
docker compose up -d postgis

# 2. Construir la imagen y ejecutar las migraciones
docker compose run --rm --build api uv run --no-sync alembic upgrade head

# 3. Levantar la API
docker compose up --build api
```

### Reinicios posteriores (sin reconstruir imagen)

```bash
docker compose up -d postgis
docker compose run --rm api uv run --no-sync alembic upgrade head
docker compose up api
```

PostGIS se inicializa localmente con una base llamada `Caja` y la extensión `postgis` habilitada.
Dentro de ella, este
microservicio administra únicamente el schema `inspecciones`; los demás schemas pueden
restaurarse o administrarse independientemente. En ambientes desplegados, `DATABASE_NAME=Caja`
debe apuntar a la base ya existente y el contenedor PostGIS local no se utiliza. En ese ambiente,
la extensión debe ser habilitada previamente por el administrador de la base de datos; Alembic no
la crea porque este microservicio administra únicamente su schema.

La variable `POSTGRES_DB` y los scripts de activación de PostGIS solo se aplican cuando el volumen
se inicializa por
primera vez. Si un volumen local anterior fue creado con otro nombre de base, debe crearse
`Caja` manualmente o reinicializarse ese volumen si sus datos son descartables.

Para detener el entorno:

```bash
docker compose down
```

Agregue `-v` únicamente si también desea eliminar el volumen local de PostGIS.

## Migraciones

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic history
uv run alembic revision -m "descripcion"
```

Alembic administra exclusivamente `inspecciones` dentro de la base `Caja`. Su tabla de control
es `inspecciones.alembic_version`; `migrations/env.py` filtra la introspección de autogenerate
para no administrar otros schemas. La única excepción de lectura entre schemas está dentro de la
definición versionada de `inspecciones.v_consulta_inventario`. No se usa
`Base.metadata.create_all()`.

## Calidad y pruebas

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

Las pruebas de API sustituyen la dependencia de base de datos en `/ready`, por lo que la suite
rápida no necesita PostgreSQL/PostGIS ni Testcontainers.

Para instalar y ejecutar los hooks locales:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Los hooks comprueban Ruff lint y Ruff format antes de cada commit.

## Arquitectura

```text
app/
├── application/               # futuros casos de uso y DTO, sin frameworks
├── domain/                    # futuras entidades, excepciones y contratos de repository
├── infrastructure/
│   ├── config/                # configuración centralizada
│   ├── database/              # pool asyncpg y futuros repositories concretos
│   └── logging/               # logging estructurado
└── presentation/api/          # FastAPI, routers, schemas y dependencias HTTP
```

Se crean archivos solo donde ya existe comportamiento. Las capas `domain` y `application` se
incorporarán al aparecer lógica real. El dominio y la aplicación no deben depender de FastAPI
ni asyncpg. Los futuros casos de uso dependerán de interfaces de repository del dominio, y las
implementaciones de infraestructura usarán SQL explícito, parametrizado y ejecutado con asyncpg.

## Logging

Los logs se serializan como JSON a stdout, con `timestamp`, `level`, `service`, `environment`,
`logger`, `message` y `event`. Cada request reutiliza `X-Request-ID` o genera un UUID, lo agrega
a sus logs y lo devuelve en la cabecera de respuesta. Esto permite que ECS/Fargate envíe stdout
a CloudWatch Logs sin archivos locales. Los errores inesperados entregan una respuesta estable
sin stack traces, credenciales ni detalles internos.
