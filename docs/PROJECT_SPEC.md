# Especificación vigente del proyecto

Este documento es el contexto permanente para desarrollar el proyecto. Consolida las decisiones vigentes, distingue las capacidades futuras de Foundation y reemplaza la necesidad de consultar el historial original. No contiene la conversación, datos personales ni metadatos de la herramienta con la que se diseñó el proyecto.

El estado comprobado de cada requisito está en [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). Los comandos de desarrollo están en [DEVELOPMENT.md](../DEVELOPMENT.md). Una capacidad descrita aquí no implica que ya exista una integración operativa.

## Objetivo y límites

Construir un sistema de análisis deportivo **prepartido** para fútbol, básquet y béisbol. Debe producir probabilidades auditables, compararlas con el mercado sin margen, conservar un historial prospectivo y permitir evaluar separadamente la calidad del modelo y la selección de apuestas simuladas.

La arquitectura prioriza point-in-time correctness, reproducibilidad, integridad histórica y separación entre predicciones, paper betting y apuestas reales. El repositorio principal es público. Las apuestas reales pertenecen a un futuro repositorio privado; no forman parte de los datos, logs, artifacts o workflows públicos.

La implementación progresa por fases. **Foundation está cerrada y Fase 2 está en curso.** Una petición posterior del usuario incorpora una web HTML de calendario, sin activar modelos ni paper. El historial conservado comienza con decisiones ya avanzadas; los detalles que no quedaron establecidos se registran como pendientes, sin atribuirles acuerdos inexistentes.

## Deportes y mercados

| Deporte | Mercados previstos |
| --- | --- |
| Fútbol | Goles totales Más/Menos; ambos anotan; corners totales y del primer tiempo; tarjetas totales; tiros al arco; remates totales |
| Básquet | Total y handicap del partido y primer tiempo; props Más/Menos de puntos, rebotes, asistencias, triples, intentos de tres y combinaciones disponibles |
| Béisbol | Ganador, run line y total de carreras |

Cada mercado conserva alcance, sujeto y estructura de resultados. No se mezclan mercados del partido con los del primer tiempo, props de jugadores distintos ni líneas diferentes.

## Arquitectura y fuentes

Un monolito Python modular ejecutado desde GitHub Actions coordina el trabajo. PostgreSQL externo, con Neon como destino previsto, contiene información estructurada y operativa. Object storage compatible con R2 conserva objetos grandes e históricos: RAW, Parquet, datasets, modelos, manifests y distribuciones. GitHub Pages sirve una aplicación estática y JSON preparados por el pipeline; nunca se conecta directamente a PostgreSQL.

El flujo es:

```text
Providers autorizados → RAW inmutable → NORMALIZED → FEATURES as_of → PREDICTIONS
                                      ↓                         ↓
                               PostgreSQL / Parquet      evaluación / paper
                                                              ↓
                                                    JSON público → Pages
```

Interfaces mínimas: `SportsDataProvider`, `OddsProvider`, `NewsProvider` y `WeatherProvider`. SofaScore es una fuente candidata de calendario/estadísticas; el dominio no depende de sus IDs o endpoints. Betano Perú es la casa principal y se admiten casas adicionales. No se definió una API alternativa concreta ni se autorizan scraping agresivo o evasión de protecciones. Noticias, lesiones, alineaciones, estadísticas y clima deben conservar su disponibilidad temporal; el clima puede importar especialmente en estadios de béisbol abiertos o de techo retráctil.

Foundation requiere interfaces y una implementación local de almacenamiento para desarrollo/pruebas. Las conexiones reales a SofaScore, Betano, Neon y R2 pertenecen a las fases que las necesitan y dependen de autorización/configuración válida.

## Identidades y correspondencias

UUID internos identifican competiciones, equipos, jugadores, estadios, eventos y ciclos. Los IDs externos solo aparecen en mappings o referencias de providers. Una correspondencia insegura no se adivina: se registra como `PENDING_REVIEW`. Los estados admiten confirmación automática suficientemente segura, confirmación manual y rechazo. Un mapping ambiguo no debe habilitar silenciosamente la ingestión de datos de otra entidad.

La identidad externa es única por proveedor, tipo e ID externo. Las temporadas se representan explícitamente para evitar mezclar años deportivos. Las competiciones y estadios conservan zona horaria; los estadios pueden registrar `OPEN`, `RETRACTABLE` o `DOME`.

## Evento, ciclo y tracking

`event` identifica el encuentro lógico. `event_cycle` identifica una programación concreta y conserva horario previsto, inicio real, zona horaria del evento, ciclo anterior y estado. Estados mínimos: `SCHEDULED`, `TRACKING`, `LOCKED`, `FINALIZED`, `POSTPONED`, `CANCELLED` y `ABANDONED`.

Un aplazamiento cierra el ciclo anterior como `POSTPONED` y crea otro ciclo `TRACKING`. Los análisis, predicciones y apuestas mantienen el ciclo original. Nunca se liquidan automáticamente contra el nuevo encuentro programado. Un abandono puede requerir revisión de liquidación; las reglas de cada casa no se inventan.

Tracking conserva selección, perfil versionado y última actividad de análisis/cuotas. En la fase operativa alimentará `tracking.json`; el scheduler podrá leer ese JSON antes de despertar Neon si no hay trabajo.

Los timestamps se almacenan en UTC. El frontend usará **America/Lima** por defecto y calculará Hoy/Mañana según ese día local, no según la fecha UTC.

## Point-in-time

Todo dato relevante conserva `occurred_at`, `available_at` y `available_at_source` (`OBSERVED` o `ESTIMATED`). Las referencias agregadas pueden ser `MIXED`. La regla es:

```text
available_at <= decision_time
```

La construcción de features y datasets pasa por una abstracción `as_of(decision_time)`; no debe consultar libremente datos actuales. Una corrección, alineación, lesión, noticia o captura recibida después de la decisión no puede entrar en esa predicción histórica. `occurred_at` no sustituye a `available_at`. Una previsión meteorológica puede describir una hora futura y haber estado disponible antes de la decisión.

El mismo corte se aplica a cuotas, features, datasets, backtests, versiones del pipeline y selección histórica de modelos/políticas. Los manifests registran inputs, hashes y versiones; se reporta la proporción de timestamps `OBSERVED`/`ESTIMATED`. Una reconstrucción estimada no se presenta como un historial observado prospectivamente.

## RAW y almacenamiento

Cada objeto RAW conserva proveedor, endpoint, parámetros, `fetched_at`, `content_hash`, `adapter_version` y `schema_version`. El normalizador también tiene versión. Los bytes publicados bajo una identidad inmutable no se reemplazan silenciosamente.

Las capturas de cuotas repetidas se conservan aunque su contenido no cambie. Puede compartirse un blob idéntico, pero siguen existiendo observaciones separadas con sus timestamps. Los parámetros y URIs guardados deben estar libres de credenciales.

Prefijos previstos: `raw/`, `parquet/`, `datasets/`, `models/`, `manifests/` y `distributions/`. PostgreSQL conserva metadata ligera y referencias, no todos los snapshots masivos. Backups y dumps pertenecen a almacenamiento privado, nunca a artifacts públicos.

## Análisis, idempotencia y fallos

Un `analysis_run` corresponde a un ciclo y puede producir varios mercados; cada modelo produce una predicción sobre un `analysis_market` concreto. Conservar `decision_time`, modo, trigger, SHA, versiones del pipeline/features/selector/políticas, calidad, frescura y proporciones de procedencia temporal.

Modos: `LIVE`, `RECONSTRUCTED`, `BACKTEST`. Triggers: `SCHEDULED`, `MANUAL`. Officiality: `PROVISIONAL`, `OFFICIAL`, `NON_OFFICIAL`. La officialización se decide al liquidar utilizando el inicio real; su regla detallada deberá versionarse antes de producir resultados oficiales. Una predicción `OFFICIAL` que sea `STALE` no se elimina de las métricas para mejorar resultados.

Estados del run: `QUEUED`, `INGESTING`, `NORMALIZING`, `FEATURES`, `PREDICTING`, `EXPLAINING`, `PUBLISHING`, `COMPLETED`, `COMPLETED_WITH_WARNINGS`, `FAILED_DATA`, `FAILED_MODEL`, `FAILED_TIMEOUT`. Las etapas conservan inicio, heartbeat, final y un error sanitizado cuando corresponda.

Claves únicas:

- Scheduled: ciclo + slot + versión de pipeline.
- Manual: ciclo + GitHub run ID + versión de pipeline.

La hora real de decisión no es una clave de idempotencia. El slot se obtiene truncando la hora real de inicio al intervalo configurado. Una ejecución tardía puede dejar un slot vacío; registrar huecos y retrasos, sin inventar capturas históricas. Un manual tiene identidad independiente del cron.

El lock por ciclo reside en PostgreSQL y conserva propietario, adquisición, heartbeat y expiración. La recuperación tras TTL no permite que un propietario anterior modifique el lock de su sucesor. La futura reconciliación marca `FAILED_TIMEOUT` cuando una etapa abandonada supera el límite versionado. `concurrency` de Actions complementa estos mecanismos; no los sustituye.

## Cuotas, de-vig y selector

Guardar cuota decimal original, probabilidad implícita, probabilidad sin vig, overround y método utilizado. Soportar mercados completos de dos y tres resultados. No formar un mercado ficticio juntando lados de distintas líneas, capturas o casas.

Representar `HALF_LINE`, `INTEGER_PUSH`, `ASIAN_QUARTER`, `MONEYLINE` y `THREE_WAY`. `line_selector_v1` selecciona **líneas numéricas half-point sin push**; reconoce y conserva líneas enteras y asiáticas, pero no las elige. Los mercados sin línea, como moneyline o tres vías sin push, pueden representarse sin fingir que son half-lines; esta interpretación de la regla final queda documentada en un ADR.

Conservar todos los candidatos, incluidos los rechazados, en RAW/Parquet. Medir `NO_ELIGIBLE_LINE_RATE` por deporte, liga y mercado; una tasa alta de rechazo de totales enteros de béisbol es evidencia para una futura v2, no motivo para cambiar silenciosamente v1.

Betano y consenso de mercado son benchmarks separados. Cada selección registra razón, métricas, captura de origen, antigüedad y frescura.

## Probabilidades, value y paper betting

`favored side` es el resultado de mayor probabilidad del modelo. `value side` tiene probabilidad del modelo superior a la del mercado sin vig. El edge en puntos porcentuales es `100 × (p_model - p_market)`; no equivale automáticamente al retorno esperado al precio ofertado.

Ejemplo: modelo OVER 57,8 % y UNDER 42,2 %; mercado sin vig OVER 61 % y UNDER 39 %. Favorece OVER, pero el value side es UNDER con +3,2 pp. La selección simulada utiliza edge, no simplemente el resultado más probable.

Las políticas previstas son:

| Política | Regla |
| --- | --- |
| `paper_all_v1` | Una unidad al lado con máximo edge positivo en una predicción oficial con línea/mercado válido y probabilidades comparables |
| `paper_recommended_v1` | La misma base y además superar `no_bet_policy_v1` |

Sin edge positivo no se crea apuesta. Las políticas son configuraciones versionadas con vigencia prospectiva. No se modifican retroactivamente después de conocer resultados. La infraestructura representa `WIN`, `LOSS`, `PUSH`, `HALF_WIN`, `HALF_LOSS` y `VOID`; la liquidación deportiva completa queda para su fase.

**Pendiente antes de activar paper:** elegir si el precio simulado será el de Betano o la mejor cuota disponible. El historial dejó esa decisión abierta. Foundation puede conservar borradores, pero no debe activar una política fingiendo que el precio fue acordado.

NO BET contempla `EDGE_INSUFFICIENT`, `DATA_QUALITY_LOW`, `MODEL_UNVALIDATED`, `OOD_HIGH`, `ENSEMBLE_UNSTABLE`, `ODDS_STALE` y `CRITICAL_CONTEXT_MISSING`. Todos los motivos se conservan junto con la versión. **Los valores numéricos de los umbrales tampoco quedaron aprobados.** Deben definirse y congelarse antes del lanzamiento prospectivo; no se optimizan usando resultados futuros.

## Modelos y evaluación

Progresión: modelos estadísticos → baseline Gradient Boosting → red tabular → componentes temporales/embeddings/contexto-noticias → consenso. Cada complejidad adicional debe demostrar mejora fuera de muestra. Una red no se promueve por su arquitectura.

Jerarquía: **log-loss → calibración → CLV → ROI**. Brier y errores de valores/distribuciones complementan el diagnóstico. Comparar con mercado sin vig y los baselines ya disponibles. No elegir modelos, mercados, thresholds o filtros solamente por ROI histórico.

Registry con artefacto y hash, SHA, feature pipeline y estados `TRAINING`, `CANDIDATE`, `VALIDATED`, `PRODUCTION`, `DEGRADED`, `NO_VALIDATED`, `RETIRED`. Deployments con vigencia y comienzo de track record prospectivo. Una versión nueva no recibe crédito por resultados anteriores a su producción.

Experimentos registran intentos, configuración, dataset manifest, ventanas, métricas y pruebas de significancia. Backtests walk-forward reportan segmentos por liga/mercado/confianza y proporciones OBSERVED/ESTIMATED. Ventanas `TRAIN`, `DEVELOPMENT`, `HOLDOUT`, `PROSPECTIVE`. El holdout final bloqueado no está disponible para evaluación normal; una futura acción manual explícita y auditada podrá desbloquearlo. El historial prospectivo oficial también es validación definitiva.

## PostgreSQL y permisos

Nueve schemas: `catalog`, `provider`, `event`, `market`, `analysis`, `ml`, `paper`, `private_betting`, `ops`. Las 47 tablas iniciales y sus responsabilidades están en [DATA_MODEL.md](../DATA_MODEL.md). Relaciones importantes deben normalizarse; JSONB se reserva para metadata flexible, manifests/resúmenes o resultados por deporte cuando una relación fija no resulta adecuada.

Roles de aplicación separados: `sports_public_worker`, `private_bets_worker`, `model_training_worker`. El worker público y el de entrenamiento carecen de acceso al schema privado. El rol público tampoco debe poder saltarse el holdout cambiando su estado. Migraciones y administración privilegiada tienen credenciales distintas de los workers.

## Apuestas reales y seguridad pública

El futuro repositorio privado contendrá workflows y datos de apuestas reales. El workflow privado escribe en Neon y exporta `real_bets.json` privado. El frontend podrá leerlo mediante GitHub con un token del usuario; sin token no expone datos ni revisiones privadas.

Tokens futuros acotados: `SPORTS_ACTIONS_TOKEN` con `Actions: write` solo en el repositorio público; `PRIVATE_BETS_TOKEN` con `Actions: write` y `Contents: read` solo en el privado. Un PAT aplica los mismos permisos a todos los repositorios seleccionados: no se utiliza un único token con una separación ficticia de permisos por repositorio.

La apuesta real apunta a predicción, mercado y ciclo, y conserva precio tomado, fecha, casa, stake/moneda y antigüedad de la observación automática más cercana. El slippage solo será comparable si esa observación es suficientemente próxima. Ninguno de esos valores llega a inputs, logs o artifacts públicos.

Colas separadas: `ops.review_queue` para mappings, datos y liquidación simulada; `private_betting.review_queue` para liquidación real/reglas privadas. La interfaz privada podrá combinarlas visualmente.

No secretos en código, logs, URIs persistidas o ejemplos; no DSN completos; no `pull_request_target`; forks y PRs no confiables sin secretos; no backups públicos. La CSP de Pages deberá declararse mediante `<meta>` y minimizar scripts externos. El HTML original es únicamente fuente local de contexto: no se publica, incorpora al frontend ni adjunta a artifacts.

## GitHub Actions, observabilidad y frontend

Foundation aportó CI: lint, formatter/check, type checking, tests y validación de migraciones/constraints con PostgreSQL temporal. La iteración web añade `pages.yml` para construir/publicar assets públicos desde main, sin secretos. Los workflows operativos futuros son `refresh_calendar`, `tracking_scheduler`, `capture_odds`, `analyze_selected`, `settle_events`, `train_models`, `backtest`, `reconcile_stale_runs` y, cuando corresponda, acceso manual privilegiado al holdout. La publicación automática de nuevos snapshots desde el pipeline queda pendiente.

Guardar GitHub run ID, attempt, trigger, SHA, tiempos y conclusión; slots llenos/vacíos/tardíos; calidad/frescura de datos; revisiones pendientes; deployments de Pages y `schema_version` de JSON. Los resúmenes de errores deben sanitizarse.

Los cron de repositorios públicos pueden desactivarse tras 60 días sin actividad. Documentar supervisión/reactivación y recuperar el trabajo mediante operaciones idempotentes. No asumir que auto-commits evitan la desactivación, ni fabricar el historial de cuotas perdido.

Pages tendrá Partidos, Análisis, Historial, Mis apuestas y Laboratorio, con interacción sobre datos estáticos optimizados. El sitio y sus manifests deben permitir seguir una predicción hasta su modelo, política, run, ciclo e inputs públicos autorizados. La web actual solo implementa Partidos, Seguimiento, Historial de ciclos y una guía de Extensión. Las vistas de análisis, evaluación, laboratorio y apuestas privadas siguen pendientes de sus fases.

## Fases y criterios de cierre

| Fase | Entregable |
| --- | --- |
| 1 — Foundation | Python modular; 47 tablas/migraciones; permisos; configuración segura; interfaces de providers/storage; invariantes y pruebas; CI; documentación |
| 2 — Calendario + providers + tracking | Fuente deportiva autorizada, normalización, calendario, mappings/revisiones, selección y tracking/ciclos |
| 3 — Odds | Capturas autorizadas, RAW/Parquet, calidad/frescura, benchmarks y selector operativo |
| 4 — Motor estadístico | Probabilidades auditables, primero fútbol, después básquet y béisbol |
| 5 — Historial y evaluación | Officialización, resultados, liquidación, políticas paper activadas prospectivamente, calibración/CLV/ROI |
| 6 — ML | GBM y luego redes/consenso sujetos a mejora fuera de muestra y holdout protegido |
| 7 — GitHub Pages | Sitio público estático, navegación e historial; extensión privada separada cuando se autorice |

Foundation debe probar como mínimo: fuga temporal, idempotencia manual/programada, aplazamientos/ciclos, locks/TTL, mappings ambiguos, permisos SQL privados, two/three-way, de-vig, half-line elegible, enteras/asiáticas no elegibles, edge/favored/value, políticas versionadas, deployment prospectivo y holdout protegido. Las migraciones se ejecutan realmente sobre PostgreSQL temporal; no basta inspeccionar su texto.

Foundation quedó cerrada y el usuario autorizó continuar. **Fase 2 está en curso**,
con el incremento manual de navegador descrito abajo. Antes de paper siguen
pendientes el precio de referencia, thresholds NO BET, reglas de officialización
y reglas de liquidación no establecidas. Son decisiones futuras explícitas.

## Decisión posterior: fuente manual mediante extensión

El usuario solicitó una extensión para consultar webs deportivas/casas y extraer
cuotas. Se adopta panel lateral MV3 junto a una pestaña, con selección explícita,
revisión y exportación JSON local; sin iframes ni evasión de protecciones. Una
captura contiene un partido o mercado, con ID público estable, origen HTTPS y
reloj declarado. No contiene cuentas, apuestas realizadas, stakes ni credenciales.

El backend exige el contrato `browser_capture_v1`, fija recepción con el reloj de
PostgreSQL y mantiene RAW inmutable antes de normalizar. La calidad manual no
se confunde con una fuente verificada. La interpretación posterior con mappings
conserva su propia disponibilidad, incluidos reprocesados. Calendario se aplica
solo tras confirmar identidades; nombres/deportes o eventos ambiguos van a
revisión. Temporadas no suministradas quedan NULL, sin inventar sus fechas.

Un aplazamiento conserva el ciclo y el tracking anteriores; una nueva fecha
prepartido crea sucesor y requiere selección explícita. FINISHED en calendario
no equivale a resultado confirmado ni liquidación. Capturas de odds se archivan
ahora por petición expresa; su integración operativa continúa en Fase 3.

La herramienta de captura es independiente de la web HTML solicitada después.
No es una fuente cron en servidor: refresh/scheduler remotos quedan pendientes de acceso
autorizado ejecutable o recepción autenticada con persistencia. No se fabrican
capturas históricas durante huecos. Véanse [ADR 0007](decisions/0007-browser-capture-provider.md)
y [BROWSER_CAPTURE.md](BROWSER_CAPTURE.md).

## Decisión posterior: web HTML ejecutable

El usuario pidió ejecutar una página HTML del proyecto dentro del repositorio.
Se incorpora `index.html` y una vista estática de los datos públicos disponibles,
con filtros, fechas America/Lima y trazabilidad de reprogramaciones por ciclo.
El calendario inicial está vacío; el ejemplo sintético solo se abre expresamente.
El navegador admite `public_calendar_v1` en memoria, sin subir datos ni conectarse
a PostgreSQL. La exportación de solo lectura y el build aplican campos y rutas
explícitos; el HTML original de contexto nunca es un asset.

El snapshot muestra estado operacional actual, no información histórica `as_of`
ni predicciones. No satisface por sí solo Fase 2 ni toda Fase 7. Se preservan los
criterios de las fases posteriores. Véanse [WEB.md](WEB.md) y
[ADR 0008](decisions/0008-static-calendar-web.md).

## Decisión posterior: escaneo automático desde la web

El usuario aclaró que la extensión debe abrir por sí sola las páginas necesarias
al iniciar un escaneo desde la web. El modo manual se conserva como alternativa;
deja de ser la única forma de captura. Las fuentes elegidas son SofaScore,
Betano Perú, Apuesta Total, Te Apuesto y Flashscore Perú, con las URLs exactas
registradas en [AUTOMATIC_SCANNING.md](AUTOMATIC_SCANNING.md).

La implementación usa una cola local de pestañas, lectores DOM declarativos
versionados, permisos por host y un puente restringido a la página del proyecto.
Una ejecución no puede inventar IDs, completar cuotas ausentes o mezclar campos
de distintos mercados. Se detiene ante accesos restringidos o datos ambiguos.
No hay evasión de CAPTCHA, sesión automatizada, clics de apuesta ni datos privados.

`browser_capture_v2` etiqueta AUTOMATIC_DOM y conserva scan/lector/perfil/hash.
La calidad es DOM_UNVERIFIED; PostgreSQL sigue fijando disponibilidad real al
recibir los datos. `browser_scan_v1` agrupa capturas sin sustituir su identidad ni
alterar las fechas originales. El normalizador v1 de capturas manuales mantiene
compatibilidad e inmutabilidad. Se conserva RAW antes de NORMALIZED.

La versión inicial solo incluía perfiles DOM. La petición posterior aporta una
extensión de referencia y exige conectores ejecutados en el navegador del usuario.
La versión 0.4 incluye SofaScore/Flashscore para calendario de fútbol de hoy y
Betano/Apuesta Total para mercados compatibles; la configuración ofrece casillas
por fuente y el sitio muestra vista previa y diagnóstico descargable. Te Apuesto
no está en la referencia y sigue sin lector. Se conservan perfiles DOM avanzados.

Los conectores consultan rutas públicas fijas o una proyección acotada del estado
de la página, sin interceptar tráfico ni exportar cuentas. La sesión ordinaria
del sportsbook solo se utiliza para sus endpoints públicos; no se recopilan
cookies/encabezados de autorización. No hay reintentos que busquen eludir un
401/403/429. `browser_capture_v3` identifica AUTOMATIC_SOURCE y SOURCE_UNVERIFIED;
el backend mantiene recibos confiables, RAW y normalización versionada. Los datos
de vista previa no sustituyen mappings ni publicación de calendario.

El desarrollo de los conectores se apoya en los formatos inspeccionados de la
referencia; su ejecución no depende del acceso del cloud a las fuentes. Las
pruebas usan fixtures, no certifican acceso real. La navegación por cada partido,
todos sus mercados y aceptación real siguen pendientes. Véanse ADRs
[0009](decisions/0009-automatic-browser-scanning.md) y
[0010](decisions/0010-browser-source-connectors.md).

## Decisiones todavía abiertas

La ausencia de una cifra o regla en este documento no autoriza a inferir que fue acordada. Estas decisiones deben cerrarse en la fase que las necesite y registrar versión, evidencia y vigencia:

| Tema | Qué falta definir |
| --- | --- |
| Acceso a fuentes | Fuente deportiva autorizada y contratos de datos; acceso a Betano u otros proveedores de cuotas; permisos/licencias de noticias y clima |
| Tracking | Cadencias por perfil, anticipación respecto al inicio, freshness y tiempos operativos de timeout/reintento |
| Correspondencias | Política de matching validada con datos; cualquier umbral de Foundation es una configuración técnica conservadora, no un acuerdo de precisión estadística |
| Selección de línea | Ranking definitivo entre candidatos elegibles y comparables, sus métricas y política de consenso entre casas |
| Paper | Fuente de precio, universo de casas, freshness y desempates antes de activar políticas |
| NO BET y confianza | Thresholds numéricos, cálculo de calidad/OOD/dispersión y reglas de contexto crítico por mercado |
| Oficialización | Selección exacta del análisis oficial respecto al inicio real y tratamiento de múltiples análisis prepartido |
| Liquidación y CLV | Reglas deportivas/de casa para abandonos, cancelaciones, push/medias liquidaciones y definición reproducible de la captura de cierre |
| ML | Ventanas concretas, datasets autorizados, criterios de promoción/calibración y procedimiento manual de acceso al holdout |
| Despliegue | Aprovisionamiento Neon/R2, retención y backups privados; permisos mínimos y exportaciones públicas verificadas |

Estas decisiones no deben resolverse retroactivamente según qué alternativa hubiera ganado más apuestas. Los defaults utilizados en tests son datos sintéticos y no activan políticas en producción.
