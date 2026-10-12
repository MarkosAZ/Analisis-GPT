# Captura manual, calendario y seguimiento

Este documento conserva el recorrido manual compatible. La extensión también
incorpora [escaneo automático](AUTOMATIC_SCANNING.md), solicitado después, con
capturas DOM `browser_capture_v2`, conectores incluidos `browser_capture_v3`
y lotes `browser_scan_v1`. El comando
`sports-capture import-scan` conserva el mismo pipeline y las mismas fronteras SQL.

Esta iteración incorpora la extensión solicitada como provider manual de Fase 2.
La [guía de la extensión](../extension/README.md) explica instalación, navegación,
selección y exportación. No requiere credenciales en el navegador.

## Recorrido operativo

1. Capturar un partido o mercado público en la extensión.
2. Revisar y descargar un `sports-capture-UUID.json` fuera del checkout.
3. Importar el archivo con `sports-capture import`.
4. En calendario, revisar mappings y confirmar identidades; reprocesar con una
   nueva clave de operación. Cada observación conserva su disponibilidad propia.
5. Seleccionar el ciclo para seguimiento y exportar `tracking.json` si se necesita.

El circuito es **archivo revisado → validación del contrato → RAW inmutable →
normalización → calendario/ciclos → tracking JSON**. La validación previa al RAW
rechaza campos desconocidos potencialmente privados; no calcula features ni
predicciones antes de persistir. Un archivo inválido se rechaza sin copiarlo a RAW.
Las cuotas permanecen archivadas, con normalización de tipos y procedencia, pero
sin inserción en `market.odds_captures`, benchmarks ni paper betting hasta Fase 3.

## Configuración y comandos

Instala con `uv sync --frozen`, migra con `uv run sports-db --directory migrations`
usando credenciales de propietario, y cambia a una conexión de runtime con rol
`sports_public_worker`. `DATABASE_URL` se obtiene del entorno. No la pases como
argumento ni la pongas en la extensión. `SPORTS_OBJECT_ROOT` apunta a almacenamiento
local privado persistente; el valor por defecto es `.local/object-storage`.

```bash
uv run sports-capture import /ruta/privada/sports-capture-UUID.json
uv run sports-capture pending-mappings
```

El importador devuelve UUID de captura/observación, disposición, razón y, cuando
existe, ciclo. Los mappings pendientes exponen únicamente los identificadores y
nombres públicos necesarios para revisarlos. Para cada mapping, elige una opción:

```bash
# Relacionar con la identidad canónica existente, tras revisar tipo y deporte:
uv run sports-capture map-entity MAPPING_UUID --sport FOOTBALL --entity-id ENTITY_UUID

# Crear una identidad nueva únicamente cuando confirmes que corresponde:
uv run sports-capture map-entity MAPPING_UUID --sport FOOTBALL --create

# Resolver el calendario; el request UUID debe ser nuevo para esta operación:
uv run sports-capture reprocess CAPTURE_UUID --request-id REQUEST_UUID

uv run sports-capture track CYCLE_UUID --status ACTIVE --request-id REQUEST_UUID
uv run sports-capture track CYCLE_UUID --status PAUSED --request-id ANOTHER_REQUEST_UUID
uv run sports-capture export-tracking .local/tracking.json
```

Los UUID en mayúsculas son placeholders. Puedes generar uno mediante
`uv run python -c 'from uuid import uuid4; print(uuid4())'`. Reutiliza el mismo
request UUID solo para reintentar **la misma** operación. La exportación rechaza
un destino existente: usa un nombre nuevo o sustituye deliberadamente tu snapshot
local después de revisarlo. No apunta automáticamente a Pages.

La confirmación de mapping se limita a pendientes; no ofrece una reasignación de
identidades confirmadas que pueda reescribir historia. Cambios de nombre/deporte,
IDs ambiguos, participantes diferentes y conflictos terminales generan `REVIEW`
y una entrada en `ops.review_queue`. La resolución administrativa de esos
conflictos y las correspondencias de eventos entre fuentes siguen pendientes.

## Semántica temporal e idempotencia

`captured_at` es declarado por el navegador; la calidad es `MANUAL_UNVERIFIED`.
La base fija `received_at` con su reloj y rechaza capturas del futuro. Una lectura
del navegador no certifica autenticidad ni simultaneidad entre campos.

`available_at` del RAW normalizado es la recepción confiable. Para usar una
interpretación con identidad/ciclo, se exige además el `available_at` de su fila
en `provider.browser_observations`. Una confirmación o relectura posterior no
vuelve disponible esa identidad en el pasado. `observations_as_of(decision_time)`
devuelve únicamente observaciones conocidas a esa fecha, con referencia al
manifest original; **no** reconstruye historia consultando el estado mutable
actual de `event_cycles`. Todavía no existe un feature builder deportivo.

El UUID identifica una observación; su hash se vincula a los bytes exactos.
Reimportar el mismo archivo devuelve el resultado inicial sin duplicados. El mismo
UUID con bytes distintos se rechaza. Una captura nueva con cuotas iguales se
conserva con otro UUID. Cambiar espacios del JSON con el mismo UUID también cambia
su hash: conserva el archivo original para reintentos.

La recepción se confirma antes de escribir objetos. Un fallo posterior conserva
esa fecha; al reintentar no cambia la metadata RAW. El caller de `BrowserIngestor`
usa una conexión autocommit para separar las transacciones. Las escrituras del
calendario se serializan con un advisory lock transaccional corto, timeout de
espera de 10 s y de sentencia de 30 s. Al morir la conexión se libera el lock.
No se crean analysis runs ficticios para usar los locks TTL de predicciones.

## Eventos y límites de esta versión

- Todas las entidades de fuentes nuevas pasan por confirmación explícita. No se
  adivina que nombres similares sean la misma identidad.
- El ID externo del evento se vincula a UUID internos mediante `event_refs`.
  Otro ID/proveedor que parezca el mismo partido queda en revisión.
- Una reprogramación prepartido cierra el ciclo previo como POSTPONED y crea
  sucesor. Se cierra su tracking; seleccionar el nuevo ciclo es explícito.
- POSTPONED sin nueva fecha conserva el ciclo cerrado hasta observar una fecha
  nueva. Una vuelta a SCHEDULED con la misma fecha requiere revisión.
- CANCELLED/ABANDONED no reabren ciclos. IN_PROGRESS bloquea el ciclo; FINISHED
  requiere inicio real, pero no confirma resultados ni liquida apuestas.
- Observaciones con `captured_at` anterior a la última aplicada se archivan como
  STALE. La ausencia de un partido en otra captura no implica cancelación.
- Temporada queda `NULL`: el formulario v1 no proporciona fechas/identidad de
  temporada y no se inventan. Las zonas de fechas son explícitas; presentación
  operativa America/Lima, sin afirmar que sea la zona del estadio.
- El modo manual no recolecta en segundo plano; el nuevo motor automático abre
  pestañas para un recorrido explícito. No hay R2 conectado, extracción desde
  iframes, lectores verificados de SofaScore/Betano ni API remota autenticada.

`tracking.json` es una lista pública versionada de ciclos seleccionados y estados;
no contiene RAW, origen, tokens, URLs, apuestas, cuotas tomadas o stakes. Es un
snapshot operacional, no un historial apto para backtest. Un futuro scheduler debe
volver a comprobar estado/inicio en PostgreSQL antes de actuar: ACTIVE puede
quedar obsoleto si no llega ninguna captura de actualización.

Para ver el calendario en la web existe un contrato distinto:
`sports-capture export-calendar .local/calendar.json`. Exporta ciclos públicos
completos y sus estados actuales; el botón **Cargar calendario** lo abre localmente
sin subirlo. No cargues capturas RAW en la web. Véase [WEB.md](WEB.md).

## GitHub Actions y siguiente incremento

CI prueba el código, migraciones, JS y UI sin secretos y empaqueta únicamente los
assets permitidos; no sube datos como artifacts. No se añade un cron que finja
poder leer la pestaña local del usuario desde GitHub Actions. `refresh_calendar`
y `tracking_scheduler` siguen pendientes hasta tener una fuente ejecutable en
servidor o un canal autenticado de recepción y almacenamiento persistente.

Para cerrar Fase 2: probar una captura autorizada real; añadir temporadas y un
flujo auditado de resolución de conflictos; configurar Neon/R2 con permisos
mínimos; definir cadencias; implementar workflows con locks, slots, reconciliación
y reactivación tras 60 días de inactividad. Un hueco de cron nunca se rellena con
cuotas actuales simulando una observación pasada.
