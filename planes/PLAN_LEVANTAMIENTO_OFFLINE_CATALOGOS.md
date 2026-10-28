# Plan de levantamientos offline, catálogos y endpoint directo provisional

## 1. Objetivo

Definir la evolución del backend de inspecciones para soportar dos formas de ingreso de un
levantamiento finalizado:

1. Un endpoint HTTP directo utilizado durante el desarrollo del formulario y mientras todavía no
   exista la sincronización offline completa.
2. Un futuro proceso de sincronización que recibirá desde el dispositivo móvil un archivo ZIP con
   inspecciones finalizadas y sus archivos asociados.

Ambas entradas deben reutilizar el mismo caso de uso de aplicación para validar y persistir un
levantamiento. El endpoint directo será provisional y estará controlado mediante una variable de
entorno, pero puede permanecer habilitado durante un periodo prolongado de desarrollo.

## 2. Decisiones de alcance

### 2.1 Responsabilidades del dispositivo móvil

Al principio de la jornada, el dispositivo descargará una copia selectiva de la información que
necesita para trabajar sin conexión. La aplicación móvil almacenará esa información localmente,
por ejemplo en SQLite o en la tecnología que defina el equipo de frontend.

Son responsabilidad exclusiva del dispositivo móvil:

- Precargar en el formulario los datos de la última inspección finalizada de la finca.
- Mantener borradores y cambios parciales del levantamiento.
- Reabrir y editar esos borradores mientras se trabaja sin conexión.
- Omitir las imágenes de la inspección anterior durante la precarga.
- Preparar posteriormente el paquete ZIP de sincronización.

Por esta razón, el backend no necesita:

- Un endpoint específico para obtener la última inspección finalizada con fines de precarga.
- Guardar levantamientos en estado borrador o `En proceso`.
- Conservar las modificaciones parciales realizadas en el dispositivo.
- Implementar la base local o decidir si el móvil usará SQLite.

### 2.2 Responsabilidades del backend

El backend solamente aceptará y persistirá levantamientos finalizados. Debe:

- Publicar el catálogo canónico de opciones del formulario.
- Validar nuevamente el levantamiento recibido, aunque haya sido validado en el móvil.
- Garantizar un solo levantamiento por inspección.
- Finalizar la inspección y ejecutar sus efectos de negocio dentro de una transacción.
- Permitir reintentos seguros de la futura sincronización.
- Persistir y relacionar fotografías y firma cuando se implemente el transporte de archivos.
- Servir la misma lógica tanto al endpoint directo como al futuro procesador del ZIP.

## 3. Arquitectura propuesta

Separar el flujo en tres componentes:

```text
POST directo (temporal) ─┐
                         ├─> FinalizarLevantamientoUseCase ─> repositorios/BD
Procesador ZIP (futuro) ─┘

GET catálogos ─────────────> CatalogoLevantamientoService ─> catálogo/BD
```

El caso de uso `FinalizarLevantamientoUseCase` no debe conocer si la información llegó mediante
HTTP, ZIP, una cola o cualquier otro mecanismo. Cada adaptador transforma su entrada al mismo
comando de aplicación.

El flag de entorno controlará solamente el adaptador HTTP directo. Nunca debe deshabilitar el caso
de uso compartido ni el futuro proceso de sincronización.

## 4. Catálogo de levantamiento

### 4.1 Nueva tabla

Crear una tabla local administrada por `ms-inspecciones`, por ejemplo:

```text
inspecciones.levantamiento_opcion
---------------------------------
id_opcion              bigserial PK
tipo_catalogo          varchar
codigo                 varchar
nombre                 varchar
requiere_cantidad      boolean
permite_descripcion    boolean
orden                  integer
es_activo              boolean
fecha_creacion         timestamptz
fecha_modificacion     timestamptz nullable
```

Restricciones mínimas:

- `UNIQUE (tipo_catalogo, codigo)`.
- `codigo` será estable y no dependerá del texto mostrado al usuario.
- Los registros usados históricamente se desactivarán; no se borrarán físicamente.
- `nombre` podrá cambiar sin modificar los JSON históricos.

Tipos de catálogo iniciales:

| `tipo_catalogo` | Opciones iniciales |
|---|---|
| `CONDICION_BIEN` | Buena, Regular, Vandalizada |
| `ESTADO_OCUPACION` | Desocupado, Ocupado, Invadido |
| `TIPO_IDENTIFICACION_OCUPANTE` | Cédula de identidad, Pasaporte |
| `PUERTA_MATERIAL` | Hierro, Multilock, Madera, Vidrio/Aluminio |
| `VENTANA_TIPO` | Vidrios fijos, Ornamentales, Verjas, Persianas, Francesa, Otros |
| `SERVICIO_PUBLICO` | Luz conectada, agua con medidor, agua con niple, agua desconectada |
| `DISTRIBUCION_INMUEBLE` | Sala, recámara, comedor, cocina, baños, depósito, portal, terraza, lavandería, piscina |
| `LIMPIEZA` | Interna, externa, retiro de enseres, limpieza de piscina |
| `CERRAJERIA_MATERIAL` | Hierro, Multilock, Madera, Vidrio/Aluminio |
| `REPARACION` | Las reparaciones indicadas por la HU 8, incluida Otras reparaciones |
| `INSPECCION_TECNICA` | Eléctrica, plomería, aire acondicionado |

Aunque algunas opciones se parezcan a catálogos de `ms-bien`, se propone que el contrato del
levantamiento tenga códigos propios y coherentes con la HU 8. Antes de sembrar los datos se debe
acordar si `CONDICION_BIEN`, `ESTADO_OCUPACION` y ambientes tendrán una única fuente maestra
compartida con `ms-bien`. No se deben mezclar silenciosamente valores como `Ocupada` y `Ocupado`.

### 4.2 Endpoint de catálogo

Crear:

```text
GET /inspeccion/levantamiento/catalogos
```

Respuesta propuesta:

```json
{
  "version": "2026-09-06T10:30:00Z",
  "catalogos": {
    "PUERTA_MATERIAL": [
      {
        "codigo": "HIERRO",
        "nombre": "Hierro",
        "requiere_cantidad": true,
        "permite_descripcion": false,
        "orden": 1
      }
    ],
    "VENTANA_TIPO": []
  }
}
```

Reglas del endpoint:

- Retornar solamente opciones activas.
- Ordenar por `tipo_catalogo`, `orden` y `nombre`.
- Incluir una versión o fecha de modificación para que la futura descarga selectiva pueda detectar
  cambios.
- Usar códigos estables en los intercambios con el móvil.
- Permanecer disponible independientemente del flag del endpoint directo.
- Ser la misma fuente de datos utilizada para construir la copia offline.

## 5. Estructura de las respuestas JSONB

Se puede mantener JSONB para almacenar las selecciones del formulario, pero se reemplazarán los
campos `Any` por modelos explícitos de Pydantic.

Ejemplo para puertas:

```json
{
  "entrada_principal": [
    {"codigo": "HIERRO", "cantidad": 1},
    {"codigo": "MADERA", "cantidad": 2}
  ],
  "traseras": [
    {"codigo": "MULTILOCK", "cantidad": 1}
  ]
}
```

Cada selección debe utilizar el `codigo` del catálogo. El backend validará:

- Que el código exista y esté activo.
- Que corresponda al tipo de catálogo esperado.
- Que no se repita dentro del mismo grupo.
- Que `cantidad` sea un entero positivo cuando la opción la requiera.
- Que las opciones `OTRO` incluyan una descripción válida.
- Que no se envíe descripción libre cuando la opción no la permita.

JSONB es apropiado mientras el levantamiento se consulte principalmente como un documento
completo. Si posteriormente se requieren reportes intensivos por material, ambiente o reparación,
se evaluará migrar las selecciones a una tabla hija normalizada.

## 6. Caso de uso único para finalizar

Crear o refactorizar un caso de uso con una interfaz equivalente a:

```text
finalizar_levantamiento(comando, actor, id_operacion)
```

El caso de uso debe:

1. Abrir una transacción.
2. Bloquear la inspección objetivo para evitar finalizaciones concurrentes.
3. Comprobar que la inspección existe y todavía puede finalizarse.
4. Comprobar, cuando aplique, que el actor sea el inspector asignado o un proceso autorizado.
5. Validar todos los campos obligatorios de la HU 8.
6. Validar los códigos recibidos contra el catálogo.
7. Insertar un único levantamiento asociado con la inspección.
8. Registrar fotografías y firma cuando el adaptador ya haya almacenado los archivos.
9. Cambiar la inspección directamente a `Finalizada`.
10. Establecer `fecha_realizada` y calcular `fecha_vencimiento` cuando corresponda.
11. Actualizar las coordenadas del inventario mediante el mecanismo de integración acordado.
12. Generar los eventos o notificaciones asociados con una inspección técnica requerida.
13. Confirmar la transacción.

No tendrá una operación de guardar borrador. Tampoco cambiará una inspección a `En proceso`.

### 6.1 Idempotencia

La futura sincronización podrá reenviar un levantamiento si pierde la conexión antes de recibir la
respuesta. Por eso cada envío debe contener un `id_operacion` UUID generado en el dispositivo.

El backend debe garantizar:

- Mismo `id_operacion` y mismo contenido: devolver el resultado anterior sin duplicar datos.
- Mismo `id_operacion` con contenido diferente: responder conflicto.
- Otra operación para una inspección ya finalizada: responder conflicto y no sobrescribir el
  levantamiento final.

La tabla y el detalle exacto del registro de idempotencia se definirán junto al diseño del paquete
de sincronización, pero el caso de uso debe admitir el identificador desde su primera versión.

## 7. Endpoint directo provisional

Conservar temporalmente:

```text
POST /inspeccion/{id_inspeccion}/levantamiento
```

Este endpoint permitirá probar el formulario y crear levantamientos finalizados sin esperar el
proceso de sincronización. Debe llamar directamente al caso de uso descrito en la sección anterior.

Cambios de contrato propuestos:

- Aceptar solamente levantamientos completos y finalizados.
- Eliminar la semántica de `accion=guardar`.
- Durante una transición, si se conserva `accion`, aceptar únicamente `finalizar` y marcar el campo
  como obsoleto.
- Recibir `id_operacion` para soportar reintentos.
- Responder `201` cuando crea el levantamiento y una respuesta idempotente cuando ya procesó la
  misma operación.
- Responder `409` si la inspección fue finalizada mediante otra operación.

### 7.1 Feature flag

Agregar a `Settings`:

```python
enable_direct_levantamiento_endpoint: bool = False
```

Variable de entorno:

```dotenv
ENABLE_DIRECT_LEVANTAMIENTO_ENDPOINT=false
```

Comportamiento:

- `true`: permite utilizar el endpoint HTTP directo.
- `false`: el endpoint directo responde `404` sin ejecutar el caso de uso.
- El valor predeterminado debe ser `false` para evitar habilitar accidentalmente una vía temporal
  en un entorno nuevo.
- Desarrollo local y ambientes de integración podrán configurarlo en `true`.
- El endpoint de catálogos no dependerá de este flag.
- El futuro consumidor del ZIP no dependerá de este flag.
- El caso de uso `FinalizarLevantamientoUseCase` no consultará este flag.

Se debe documentar la variable en `.env.example`, `README.md` y la guía de despliegue.

## 8. Futuro proceso de sincronización ZIP

Cuando se implemente, el procesador será otro adaptador del mismo caso de uso. Sus
responsabilidades serán:

- Recibir y almacenar temporalmente el ZIP.
- Validar tamaño, extensión, checksum y estructura del paquete.
- Proteger contra rutas inseguras dentro del ZIP y archivos comprimidos maliciosos.
- Leer un manifiesto con versión de contrato, dispositivo, usuario y operaciones.
- Cargar fotografías y firmas al almacenamiento definitivo.
- Convertir cada levantamiento a `FinalizarLevantamientoCommand`.
- Invocar el caso de uso individualmente o por lotes con una política transaccional definida.
- Registrar resultados por operación para permitir reintentos parciales.
- Generar un resumen de aceptados, duplicados y rechazados.

El diseño exacto del ZIP queda fuera de esta fase, pero el endpoint directo no debe incorporar
reglas que después impidan compartir la lógica.

## 9. Pruebas requeridas

### Catálogos

- Retorna todas las agrupaciones sembradas.
- Excluye opciones inactivas.
- Mantiene códigos y orden estables.
- Rechaza códigos duplicados durante la migración o administración.

### Validación del levantamiento

- Rechaza códigos inexistentes, inactivos o pertenecientes a otra agrupación.
- Rechaza cantidades cero, negativas o no enteras.
- Rechaza opciones duplicadas.
- Valida las descripciones de `OTRO`.
- Exige todos los campos, fotografías y firma definidos como obligatorios.
- Aplica las reglas condicionales de ocupante e inspección técnica.

### Persistencia y estado

- Inserta un solo levantamiento por inspección.
- Finaliza la inspección en la misma transacción.
- No crea estados provisionales ni borradores.
- No sobrescribe un levantamiento ya finalizado.
- Soporta dos solicitudes concurrentes sin duplicar ni perder información.

### Idempotencia

- Repetir el mismo `id_operacion` devuelve el mismo resultado.
- Reutilizar el identificador con otro contenido produce conflicto.
- Una operación diferente para una inspección finalizada produce conflicto.

### Feature flag

- Con el flag habilitado, el endpoint directo procesa el levantamiento.
- Con el flag deshabilitado, el endpoint directo no es utilizable.
- El catálogo sigue disponible con el flag deshabilitado.
- El caso de uso compartido funciona sin depender del flag.

## 10. Orden recomendado de implementación

1. Acordar códigos canónicos y propiedad de los catálogos compartidos con `ms-bien`.
2. Crear la migración de `levantamiento_opcion` y sembrar las opciones de HU 8.
3. Implementar `GET /inspeccion/levantamiento/catalogos`.
4. Crear modelos Pydantic tipados para sustituir los campos `Any`.
5. Refactorizar la lógica actual a `FinalizarLevantamientoUseCase` sin soporte de borradores.
6. Agregar idempotencia y bloqueo de la inspección dentro de la transacción.
7. Adaptar el endpoint directo para usar el caso de uso.
8. Agregar `ENABLE_DIRECT_LEVANTAMIENTO_ENDPOINT` y su documentación.
9. Implementar las pruebas de catálogo, contrato, finalización, concurrencia y flag.
10. Diseñar e implementar en una fase posterior el adaptador de sincronización ZIP.

## 11. Criterios de terminación de esta fase

La primera fase estará terminada cuando:

- El catálogo completo de HU 8 tenga códigos estables y esté disponible mediante API.
- El levantamiento deje de aceptar estructuras arbitrarias en los campos JSONB.
- El endpoint directo solamente cree levantamientos finalizados.
- No se persistan borradores en PostgreSQL.
- La finalización sea transaccional e idempotente.
- El endpoint directo pueda habilitarse y deshabilitarse mediante la variable de entorno.
- La lógica central pueda invocarse posteriormente desde un procesador ZIP sin duplicación.
