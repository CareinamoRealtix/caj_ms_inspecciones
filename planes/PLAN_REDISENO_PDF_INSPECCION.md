# Plan: Rediseño del PDF de Informe de Inspección

Objetivo: que el PDF generado por `GET /v1/inspeccion/{id_inspeccion}/pdf` replique el
diseño y contenido de la plantilla "Informe de Inspección" (Gerencia de Bienes Adquiridos).

Orden sugerido: primero cerrar los **datos faltantes** (para no maquetar con información
incompleta), luego el **rediseño visual**.

## Fase 1 — Completar datos faltantes (backend)

- [x] Unir `inspecciones.v_consulta_inventario` en el query de `get_detalle`
      (`app/infrastructure/database/inspeccion_repository.py:448`) por `id_bien_inventario`
      para traer `provincia`, `distrito`, `corregimiento`, `barriada_sector`, `direccion`,
      `numero_lote`.
- [x] Agregar esos campos a `DetalleInspeccionResponse` / mapeo en
      `InspeccionService.get_detalle` (`app/application/inspeccion_service.py:877`).
- [x] Resolver el nombre del inspector (`displayName`) a partir de `email_inspector` usando
      el cliente de Azure AD existente (`app/infrastructure/clients/azure_ad_client.py`), para
      mostrar "Francisco De La Rosa" en vez del correo. Resuelto en el router (`get_pdf`), con
      fallback al correo si Azure AD no está disponible o falla la consulta.
- [x] Confirmar el mapeo de "No. de Identificación de Inspección" (usar `numero_inspeccion`
      con el prefijo `INSP-` o formato que se defina). Se formatea como `INSP-XXX`
      (zero-padded a 3 dígitos) dentro del generador de PDF.
- [x] Actualizar/crear tests del servicio de inspecciones y del repositorio que cubran los
      nuevos campos en `get_detalle` (`tests/application/test_inspeccion_service.py`,
      `tests/infrastructure/test_inspeccion_ruta.py`).
- [x] Conseguir el archivo del logo institucional (Caja de Ahorros) para incrustarlo en el PDF.
      Guardado en `app/presentation/pdf/assets/logo_caja_ahorros.png`; el generador lo detecta
      automáticamente (si el archivo no existe, el encabezado cae a solo-texto sin romper el
      diseño).

## Fase 2 — Rediseño visual del PDF (reportlab)

- [x] Encabezado con logo institucional (opcional/automático) + título "INFORME DE
      INSPECCIÓN" + subtítulo "Gerencia de Bienes Adquiridos".
- [x] Franja superior: No. de Identificación de Inspección | Fecha — Inspector | Tipo.
- [x] Sección "DATOS DEL BIEN": No. de Finca, Provincia, Distrito, Corregimiento,
      Barriada/Sector/PH, Calle/No. de Casa.
- [x] Sección "DETALLES DEL INMUEBLE": Estado de Ocupación, Condición del bien, Nombre del
      Ocupante, Cédula (fondo gris, igual que la plantilla).
- [x] Tabla "Puertas" (Puerta Principal vs. Traseras, materiales según catálogo
      `PUERTA_MATERIAL`) + tabla "Tipo de Ventanas" (según catálogo `VENTANA_TIPO`). Ambas
      tablas son data-driven contra `levantamiento_opcion`, no hardcodeadas.
- [x] Línea "Servicios Públicos".
- [x] Sección "DISTRIBUCIÓN": data-driven contra el catálogo `DISTRIBUCION_INMUEBLE`
      (Sala, Recámara, Comedor, Cocina, Baños, Depósito, Portal, Terraza, Lavandería, Piscina).
      Nota: "Estacionamientos" y "Balcón" de la plantilla de referencia no existen hoy en el
      catálogo `DISTRIBUCION_INMUEBLE` de la base de datos; si se agregan como códigos nuevos,
      aparecerán automáticamente en el PDF sin tocar el generador.
- [x] Sección "SERVICIOS REQUERIDOS" (Limpieza, Cerrajería, Reparación, Inspección Técnica)
      como lista con detalle, agrupando `servicios_requeridos` por su catálogo de origen.
- [x] Sección "OBSERVACIONES" (texto libre del levantamiento).
- [x] Página 2 — "REGISTRO FOTOGRÁFICO": grid de fotos (3 columnas) descargando cada
      `url_s3` de `fotografias`, con su nombre/etiqueta debajo; placeholder gris si la
      descarga falla.
- [x] Espacio de firma digital (embebe `url_firma_inspector` si existe) + nombre del
      inspector al pie.
- [x] Ajustar tipografía y colores para acercarse a la plantilla (azul institucional en
      encabezados de sección, grises en celdas de datos clave).
- [x] Tests nuevos: `tests/presentation/test_inspeccion_pdf.py` (generador de PDF) y
      `tests/api/test_pdf_inspeccion.py` (endpoint `/pdf`, incl. fallback de Azure AD y 404).
- [ ] QA manual: generar un PDF de una inspección real (con levantamiento y fotos reales) y
      comparar visualmente contra la plantilla de referencia una vez desplegado.

## Implementación

- Nuevo módulo `app/presentation/pdf/inspeccion_pdf.py`: contiene todo el layout (reportlab
  platypus), separado del router para mantenerlo legible.
- `app/presentation/api/routers/inspecciones.py`: el endpoint `GET /{id_inspeccion}/pdf` ahora
  resuelve el nombre del inspector, obtiene los catálogos de levantamiento, descarga fotos y
  firma de forma concurrente (`httpx.AsyncClient` + `asyncio.gather`), y delega el armado del
  PDF a `generar_pdf_inspeccion`.
- Verificado visualmente renderizando el PDF a imagen (`pdftoppm`) con datos de ejemplo
  equivalentes a la plantilla de referencia: layout, colores y secciones coinciden.
