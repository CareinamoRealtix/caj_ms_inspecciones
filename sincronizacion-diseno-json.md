# Diseño del JSON de sincronización (endpoint provisional)

## Contexto

Este documento propone el formato del JSON que devolverá un endpoint **provisional**
de sincronización (`GET /sincronizacion` o similar, a definir), que sirve como
sustituto temporal del proceso real que correrá en AWS Batch (el cual generará un
JSON equivalente y lo dejará en CloudFront para descarga desde el móvil).

El endpoint recibe el **email del inspector** y responde en un solo JSON:

- Las inspecciones programadas para **hoy** para ese inspector.
- La información de "vista de finca" (inventario completo del bien: ubicación,
  estatus, condición, ocupación, coordenadas, etc.) para cada una de esas
  inspecciones.
- Los catálogos que esas inspecciones necesitan para poder diligenciarse offline
  (tipos de inspección, opciones de checklist del levantamiento, catálogos de
  inventario/finca usados como listas desplegables).

No incluye fotografías (son pesadas y no aplican a un précargue de formulario) ni
el dump completo de catálogos de dominio para *todas* las inspecciones del
sistema — esto es una versión acotada al día actual y al inspector solicitado,
pensada para probar el flujo antes de construir el job real de AWS Batch.

### Alcance decidido

- Solo se descargan **inspecciones programadas**. El HU.6 confirma que la app
  móvil tiene únicamente cuatro módulos (inspecciones programadas, inspecciones
  finalizadas, rutas de recorrido, sincronización); las menciones sueltas a
  "inspecciones no programadas" (HU.8) e "inspecciones periódicas programadas"
  (HU.12) no corresponden a un módulo ni a un criterio de aceptación propio —
  son texto mal redactado en la HU, no un bloque a modelar aparte. La
  periodicidad ya vive como atributo (`id_periodicidad`) de cada inspección
  programada.
- **Rango de fecha**: el día actual (`hoy`) en el momento en que se invoca el
  endpoint — se calcula en el servidor, no se recibe como parámetro ni se
  amplía a vencidas/pendientes de días anteriores.
- **Identidad de "finca"**: la combinación `id_bien_inventario` + `numero_finca`.
  El negocio le llama "finca" pero un mismo bien puede tener más de una, así que
  esa combinación es la llave real (no `id_bien_inventario` solo).
- **`ultimo_levantamiento`**: se toma de la última inspección con estado
  **Finalizado** para esa combinación bien + finca (no de cualquier estado).
- **No se incluyen "inspecciones finalizadas"** en este JSON de descarga. Ese
  módulo se llena localmente en el dispositivo cuando el inspector completa el
  formulario de levantamiento (botón "Finalizar"); es un flujo de subida
  (upload), no de este endpoint de sincronización de bajada.
- **Catálogos de inventario**: se obtienen del catálogo/schema `bien` que ya
  existe en la base de datos (mismo origen que `v_consulta_inventario`); no se
  construye un cliente HTTP hacia un futuro `ms-bien`.
- **Rutas óptimas (HU.11)**: en esta versión provisional se retorna la clave
  vacía/placeholder (`"rutas_optimas": []`). La geometría y la regla de cálculo
  de ruta óptima quedan pendientes de definir; se deja el campo en el contrato
  para que el móvil ya lo contemple al construir su modelo local.

## Hallazgos relevantes de la base actual

- No existe hoy un cliente HTTP hacia un microservicio de "bienes": la
  integración es vía una vista SQL propia, `inspecciones.v_consulta_inventario`,
  que cruza tablas del schema `bien` (mismo Postgres). Esa vista es la fuente más
  natural para la "vista de finca" de este endpoint provisional.
- La forma más parecida a "una inspección completa" que ya existe es
  `DetalleInspeccionResponse` (`app/presentation/api/schemas/inspecciones.py`),
  que ya combina inspección + inventario (vista) + levantamiento + fotos. El
  payload de sincronización reutiliza esa misma composición, quitando fotos y
  agregando el envoltorio de sincronización.
- El catálogo de checklist (`inspecciones.levantamiento_opcion`, expuesto hoy en
  `GET /levantamiento/catalogos`) es el que un formulario offline necesita para
  pintar las opciones de cada pregunta.
- HU.8 (histórico de finca) pide precargar en el formulario los datos del
  **último levantamiento realizado sobre esa finca**, sin imágenes — se incluye
  como bloque opcional dentro de cada inspección.

## Estructura propuesta

Orden de las claves de nivel superior, pensado para que el cliente pueda
**cargar catálogos primero** (y así tener las tablas de lookup listas) **antes**
de parsear las inspecciones que referencian esos catálogos por código:

```jsonc
{
  "meta": {
    "email_inspector": "juan.perez@ejemplo.com",
    "fecha_referencia": "2026-09-13",        // hoy, calculado en el servidor al momento de la llamada (no es un parámetro)
    "fecha_generacion": "2026-09-13T14:32:07Z", // cuándo se generó este JSON
    "total_inspecciones": 4
  },

  "catalogos": {
    "version": "2026-09-13T14:32:07Z", // timestamp de generación, igual patrón que GET /levantamiento/catalogos (no es hash de contenido)
    "tipos_inspeccion": [
      { "id_tipo_inspeccion": 1, "nombre": "Inicial", "descripcion": "...", "permite_descripcion_libre": false }
    ],
    "periodicidades": [
      { "id_periodicidad": 1, "nombre": "Mensual", "dias_vigencia": 30 }
    ],
    "rutas": [
      { "id": "uuid", "codigo": "RUTA-001", "nombre": "Ruta Centro" }
    ],
    "levantamiento_opciones": {
      // agrupado por tipo_catalogo, igual que GET /levantamiento/catalogos
      "CONDICION_BIEN": [
        { "codigo": "BUENO", "nombre": "Bueno", "requiere_cantidad": false, "permite_descripcion": false, "orden": 1 }
      ],
      "ESTADO_OCUPACION": [ /* ... */ ],
      "TIPO_IDENTIFICACION_OCUPANTE": [ /* ... */ ],
      "SERVICIO_PUBLICO": [ /* ... */ ],
      "PUERTA_MATERIAL": [ /* ... */ ],
      "UBICACION_PUERTA": [ /* ... */ ],
      "VENTANA_TIPO": [ /* ... */ ],
      "CERRAJERIA_MATERIAL": [ /* ... */ ],
      "LIMPIEZA": [ /* ... */ ],
      "REPARACION": [ /* ... */ ],
      "DISTRIBUCION_INMUEBLE": [ /* ... */ ],
      "INSPECCION_TECNICA": [ /* ... */ ]
    },
    "catalogos_inventario": {
      // catálogos del lado bien/finca usados como listas desplegables o para traducir códigos
      "estatus_bien_inventario": [ { "id": 1, "nombre": "...", "color_badge": "#..." } ],
      "estado_inventario": [ { "id": 1, "nombre": "..." } ],
      "condicion_bien": [ { "id": 1, "nombre": "..." } ],
      "estatus_ocupacion": [ { "id": 1, "nombre": "..." } ],
      "tipo_ambiente": [ { "id": 1, "nombre": "..." } ],
      "provincias": [ { "id": 1, "nombre": "..." } ],
      "distritos": [ { "id": 1, "id_provincia": 1, "nombre": "..." } ],
      "corregimientos": [ { "id": 1, "id_distrito": 1, "nombre": "..." } ]
    }
  },

  "rutas_optimas": [
    // placeholder: en esta versión provisional siempre vacío.
    // HU.11 pide geometría/puntos por día para trazar la ruta en el mapa;
    // queda pendiente de definir la fuente y el formato.
  ],

  "inspecciones": [
    {
      "id_inspeccion": "uuid",
      "numero_inspeccion": 1023,
      "fecha_programada": "2026-09-13",
      "fecha_vencimiento": "2026-09-20",
      "origen": "MOVIL",
      "id_tipo_inspeccion": 1,          // referencia a catalogos.tipos_inspeccion
      "descripcion_tipo": null,
      "id_periodicidad": 1,             // referencia a catalogos.periodicidades, o null
      "ruta_id": "uuid",                // referencia a catalogos.rutas
      "ruta_nombre": "Ruta Centro",

      "finca": {
        // proyección de inspecciones.v_consulta_inventario para este bien/finca
        "id_bien_inventario": "uuid",
        "id_bien": "uuid",
        "numero_finca": "12345",
        "numeros_finca": ["12345", "12346"],
        "nombre_deudor": "...",
        "numero_prestamo": "...",
        "tipo_propiedad": "...",
        "direccion": "...",
        "provincia": "...",
        "distrito": "...",
        "corregimiento": "...",
        "barriada_sector": "...",
        "numero_lote": "...",
        "latitud": 8.983,
        "longitud": -79.519,
        "url_ubicacion_geoespacial": "...",
        "id_estatus_bien": 1,
        "estatus_bien": "...",
        "color_badge": "#...",
        "id_estado_inventario": 1,
        "estado_inventario": "..."
      },

      "ultimo_levantamiento": {
        // precargue según HU.8: última inspección con estado Finalizado para
        // esta combinación id_bien_inventario + numero_finca (no cualquier
        // inspección del bien), sin fotos
        "fecha_levantamiento": "2026-08-10",
        "coordenadas": "8.983,-79.519",
        "condicion_bien": "BUENO",
        "estado_ocupacion": "OCUPADO",
        "nombre_ocupante": "...",
        "distribucion_inmueble": [ /* ... */ ],
        "servicios_publicos": [ /* ... */ ],
        "observaciones": "..."
        // sin url_firma_inspector ni fotografías
      }
    }
  ]
}
```

### Justificación del orden interno de cada inspección

1. **Identificadores y programación** primero (`id_inspeccion`, `numero_inspeccion`,
   fechas, tipo, periodicidad, ruta) — es lo mínimo para listar/ordenar
   inspecciones en el móvil sin tener que mirar el resto del objeto.
2. **`finca`** después — es la info de solo lectura que el formulario necesita
   mostrar/prellenar (inventario, ubicación, estatus).
3. **`ultimo_levantamiento`** al final y como bloque opcional (`null` si la
   finca nunca ha sido inspeccionada) — es el precargue editable, conviene que
   quede claramente separado de los datos de solo lectura de `finca`.

### Versión de catálogos

Se agrega `catalogos.version` como timestamp simple, igual al patrón ya usado en
`GET /levantamiento/catalogos` (`app/application/inspeccion_service.py:994-1010`):
`version = datetime.now(UTC)` al momento de generar la respuesta. **Ojo**: esto
no es un hash de contenido ni se basa en un `updated_at` de la base — es solo la
hora de generación, no permite detectar si el catálogo realmente cambió (dos
llamadas seguidas sin cambios devuelven `version` distinto). Se deja así por
consistencia con lo existente; el fingerprint real de contenido queda pendiente
para cuando se construya el job real de AWS Batch, si en ese momento se decide
que hace falta.

Una vez valides el formato, implemento el endpoint provisional
(`GET`, con `email_inspector` como query param) que arma este JSON reutilizando
`inspeccion_repository.py` y las queries/vistas ya existentes.
