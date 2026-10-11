# Modelo de datos

PostgreSQL conserva el estado estructurado del sistema. El contrato funcional está en [PROJECT_SPEC](docs/PROJECT_SPEC.md); las migraciones SQL son la definición ejecutable de columnas, constraints y permisos. Las 47 tablas funcionales solicitadas se distribuyen en nueve schemas. El runner añade `ops.schema_migrations` como registro técnico de versiones y checksums; no es una tabla deportiva adicional.

## Catálogo y proveedores

| Tabla | Responsabilidad y vínculos |
| --- | --- |
| `catalog.sports` | FOOTBALL, BASKETBALL y BASEBALL |
| `catalog.entities` | UUID y tipo común de equipo, jugador, competición o estadio |
| `catalog.competitions` | Entidad, deporte, nombre canónico, país, tipo y zona horaria |
| `catalog.seasons` | Temporada de una competición y fechas |
| `catalog.teams` | Entidad deportiva de equipo |
| `catalog.players` | Entidad deportiva de jugador |
| `catalog.venues` | Estadio, ubicación, zona horaria y tipo de techo |
| `provider.providers` | Catálogo SPORTS_DATA, ODDS, NEWS, WEATHER |
| `provider.entity_mappings` | Identidad externa → entidad interna, confianza, método y revisión |
| `provider.event_refs` | Referencias externas al ciclo y primeras/últimas observaciones |

Los IDs externos no son PK internas. El mapping externo es único por proveedor, tipo e ID. La referencia a un evento debe resolver su ciclo correcto aun cuando el proveedor reutilice su ID después de un aplazamiento.

## Eventos

| Tabla | Responsabilidad y vínculos |
| --- | --- |
| `event.events` | Identidad lógica: deporte, competición y temporada |
| `event.event_participants` | Equipos HOME/AWAY y orden |
| `event.event_cycles` | Programación, ciclo anterior, timestamps, estadio y estado |
| `event.tracking` | Selección y perfil de seguimiento por ciclo |
| `event.event_results` | Resultado confirmado del ciclo, inicio real y URI de detalle |

El número de ciclo es único dentro del evento. Reprogramar conserva el mismo evento pero crea un ciclo distinto. Las referencias históricas nunca se trasladan. Los resultados, análisis y apuestas deben corresponder al mismo ciclo para ser evaluables.

## Mercados y precios

| Tabla | Responsabilidad y vínculos |
| --- | --- |
| `market.bookmakers` | Casas, jurisdicción y casa principal |
| `market.market_definitions` | Código, deporte, alcance, sujeto y estructura de resultados |
| `market.odds_captures` | Observación de cuotas, ciclo, proveedor, hash/URI y calidad |
| `market.selected_quotes` | Precio de la casa elegido para un mercado/línea y captura |
| `market.selected_quote_outcomes` | Cada resultado, cuota original, probabilidad implícita y sin vig |
| `market.market_benchmarks` | BETANO o MARKET_CONSENSUS, método y frescura |
| `market.benchmark_outcomes` | Probabilidades sin vig y fair odds por resultado |

Capturar dos veces el mismo precio crea dos observaciones. Los hashes de contenido no son una clave única de observación. Las probabilidades deben ser finitas, válidas y comparables dentro de un mercado completo. Las líneas enteras/asiáticas se representan aunque v1 no las seleccione.

## Análisis

| Tabla | Responsabilidad y vínculos |
| --- | --- |
| `analysis.analysis_runs` | Ciclo, decisión, trigger, versiones, SHA, estados y calidad |
| `analysis.analysis_stages` | Inicio, heartbeat, fin y fallo sanitizado de cada etapa |
| `analysis.input_refs` | Procedencia y disponibilidad de cada dominio utilizado |
| `analysis.manifests` | URI/hash del manifiesto completo del run |
| `analysis.analysis_markets` | Mercado/sujeto, línea elegida, elegibilidad, candidatos y calidad |
| `analysis.model_predictions` | Modelo/rol, resumen de distribución, favorecido, confianza y NO BET |
| `analysis.prediction_outcomes` | Probabilidades por resultado y fair odds |
| `analysis.prediction_edges` | Comparación con cada benchmark, edge y value side |
| `analysis.prediction_evaluations` | Resultado observado, log-loss/Brier/errores e inclusión en métricas |

La cadena de trazabilidad es `prediction → analysis_market → analysis_run → event_cycle → event`. Una apuesta apunta a la predicción concreta, no solamente al run que contiene mercados heterogéneos.

Índices únicos parciales distinguen scheduled `(event_cycle_id, scheduled_slot, pipeline_version)` y manual `(event_cycle_id, github_run_id, pipeline_version)`. Los campos de trigger obligatorios no pueden quedar nulos para eludir la unicidad.

Las referencias temporales conservan `available_at` y calidad OBSERVED/ESTIMATED/MIXED según su granularidad. La metadata de datos RAW/normalizados es suficiente para reconstruir el conjunto usado; esto no convierte la migración en un feature store deportivo terminado.

## ML y evaluación

| Tabla | Responsabilidad y vínculos |
| --- | --- |
| `ml.model_families` | Familia por deporte/mercado/rol y, cuando aplique, competición |
| `ml.model_versions` | Versión, estado, artefacto/hash, SHA, features y métricas |
| `ml.model_deployments` | Vigencia de una versión y comienzo de track record prospectivo |
| `ml.evaluation_windows` | TRAIN/DEVELOPMENT/HOLDOUT/PROSPECTIVE y bloqueo |
| `ml.experiment_runs` | Intento, configuración/dataset, ventana, métricas y significancia |
| `ml.backtest_runs` | Backtest temporal y referencias a resultados detallados |

Los deployments no atribuyen resultados anteriores a una versión futura. El acceso normal no debe poder desbloquear un holdout ni leer resultados de evaluación asociados a una ventana bloqueada. La administración privilegiada es distinta del worker público.

## Paper y área privada

| Tabla | Responsabilidad y vínculos |
| --- | --- |
| `paper.paper_policies` | Versión, vigencia, selección, fuente de precio, stake y congelación |
| `paper.paper_bets` | Política/predicción, resultado seleccionado, precio y stake simulado |
| `paper.paper_bet_settlements` | Liquidación versionada WIN/LOSS/PUSH/HALF_WIN/HALF_LOSS/VOID |
| `private_betting.real_bets` | Apuesta real, precio tomado, stake/moneda y contexto de captura |
| `private_betting.review_queue` | Revisiones exclusivamente privadas |

Las políticas paper no se activan hasta resolver el precio y congelar la configuración. Las tablas privadas existen para soportar la futura separación; no se cargan apuestas reales en este repositorio. El stake simulado de una unidad no representa capital real.

## Operación

| Tabla | Responsabilidad y vínculos |
| --- | --- |
| `ops.event_locks` | Propietario, adquisición, heartbeat, expiración y protección contra propietarios antiguos |
| `ops.review_queue` | Revisiones públicas de mapping, datos y liquidación simulada |
| `ops.github_runs` | Workflow, run ID/attempt, trigger, SHA, tiempos y conclusión |
| `ops.cron_slots` | Slots y evidencia de ejecuciones/huecos/retrasos |
| `ops.page_deployments` | SHA, versión del contrato y tiempos de publicación |

Los locks se adquieren mediante operaciones atómicas de PostgreSQL. Su vigencia, renovación y liberación verifican al propietario; la limpieza física inmediata de una fila expirada no es necesaria para permitir la recuperación.

Las funciones de locks devuelven un `fencing_token` que cambia en cada adquisición. El llamador debe conservarlo y presentarlo al renovar/liberar; así un proceso atrasado no puede modificar la concesión de su sucesor. El TTL es una duración operativa, no evidencia de que el análisis haya terminado. El reconciliador de runs será un servicio separado en su fase.

Antes de persistir outputs, el writer debe ejecutar `ops.assert_event_lock(cycle,
owner, token)` **dentro de la misma transacción**. La función bloquea la fila de la
concesión hasta commit. Los grants SQL no fuerzan por sí solos que cada futuro
writer llame a este contrato; se comprobará al incorporar los repositorios de
persistencia en Fase 2.

Las probabilidades se validan como vectores completos al finalizar la transacción.
El overround SQL se guarda como fracción (`0.05`), mientras que el helper Python
expone `overround_pp` en puntos (`5`). El edge usa puntos porcentuales en ambos.
`paper_bets` referencia explícitamente quote y benchmark. Su `placed_at` representa
el instante simulado de decisión, y puede preceder a `generated_at`; la inserción
del ledger oficial sucede después de la officialización y utiliza la política que
ya estaba vigente en aquella decisión. No activa ni retoca una política histórica.

## Migraciones y validación

`migrations/0001_foundation.sql` define la estructura y mecanismos de integridad; `migrations/0002_permissions.sql` define roles/permisos. La ejecución y las pruebas de integración requieren PostgreSQL real. No se considera validada una migración únicamente porque un parser acepte su sintaxis.

`0003_historical_integrity.sql` añade vectores completos, procedencia de modelos,
referencias de paper, RLS de evaluaciones y recuperación de locks tras esperas.
`0004_quote_and_evaluation_guards.sql` valida la matemática de de-vig y las fechas
de snapshots, y protege etiquetas por fecha de decisión y ciclo.

`0005_browser_capture.sql` añade tres tablas (50 de dominio en total, más
`ops.schema_migrations`): `provider.browser_captures` fija UUID, hash y recepción;
`provider.browser_observations` conserva interpretaciones inmutables, ciclo,
manifest, versión y disponibilidad; `ops.tracking_commands` audita operaciones
idempotentes de selección/pausa. La recepción usa el reloj de PostgreSQL.
`0006_browser_review_audit.sql` vincula revisiones públicas a observaciones y
protege el ledger de comandos. No añade permisos sobre `private_betting`.

En el provider manual las temporadas no proporcionadas permanecen NULL. El
tracking pertenece a un ciclo y no se transfiere automáticamente tras aplazarse.
Un estado FINISHED del calendario no crea resultados confirmados ni liquidaciones.

`public_calendar_v1` es un contrato de exportación, no una nueva tabla. Expone
identidad pública del evento/ciclo, deporte, competición, equipos, fechas,
estados y `last_observed_at`. Este último es la disponibilidad de la última
observación APPLIED vinculada a ese ciclo; no la fecha de cada mutación del estado.
`generated_at` fija la generación de la vista actual. No se utiliza este snapshot
para datasets ni backtesting; estos requieren el ledger temporal `as_of`.

Las credenciales de migración no deben ser las de runtime público. Los detalles de ejecución y versión mínima están en [DEVELOPMENT.md](DEVELOPMENT.md). Los resultados de validación y cualquier limitación pendiente se registran en [IMPLEMENTATION_STATUS](docs/IMPLEMENTATION_STATUS.md).

El runner toma un advisory lock transaccional y verifica el SHA-256 del historial aplicado. Repetir una migración ya aplicada es un no-op; modificar, eliminar o insertar fuera de orden una versión histórica produce un error. Los cambios futuros se agregan en una nueva migración. Las pruebas usan una base temporal independiente, nunca un Neon de producción.
