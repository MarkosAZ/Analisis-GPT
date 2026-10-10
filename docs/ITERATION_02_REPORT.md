# Iteración 02 — Extensión y calendario manual

## Proyecto y fase

Sistema prepartido para fútbol, básquet y béisbol con providers intercambiables,
RAW reproducible, PostgreSQL operacional, objetos históricos y futura publicación
estática. Predicciones, paper y apuestas reales son dominios separados. Todo uso
histórico debe respetar disponibilidad en `decision_time` y pertenencia al ciclo.

Foundation estaba completada con cuatro migraciones, 47 tablas de dominio,
invariantes temporales/mercados/gobernanza, roles privados, storage local, CI y
181 pruebas. No había provider deportivo operativo, calendario, tracking ni UI.
El contexto original ya estaba consolidado; se preserva el HTML fuera del repo.

El usuario autorizó continuar y pidió una extensión para ver páginas deportivas
y extraer cuotas. Esta iteración implementa un **incremento de Fase 2**, con
captura RAW de cuotas anticipada por esa petición. Fase 2 no queda cerrada:
automatización remota, temporadas y resolución completa de conflictos siguen
pendientes. No se ha pasado a modelos o paper betting.

## Implementado

- Extensión MV3 con panel lateral en español, apertura de páginas en pestañas,
  selección de texto visible por acción explícita, cancelación, vista previa,
  confirmación y descarga JSON. Permisos activeTab/scripting/sidePanel, sin hosts
  permanentes ni claves. No incrusta ni copia la página original.
- Contrato versionado de calendario y cuotas, validación estricta y rechazo de
  campos extra. Tipos two/three-way, half, integer y asian conservados; no cambia
  la elegibilidad del selector existente ni calcula un benchmark para push.
- Recepción confiable SQL, RAW inmutable, manifests y normalización tipada.
  El UUID se liga a los bytes exactos. Reintentos y concurrencia no duplican la
  observación; precios iguales capturados de nuevo sí conservan observaciones.
- Confirmación explícita de entidades, creación de eventos y ciclos, revisión
  de conflictos, rechazo de capturas antiguas y transiciones terminales seguras.
  Un aplazamiento/reprogramación no mueve predicciones del ciclo anterior.
- Tracking por ciclo con comandos idempotentes y auditados, pausa y exportación
  `tracking_v1` de campos públicos. Tras reprogramar, el nuevo ciclo se selecciona
  explícitamente. FINISHED del calendario no confirma resultados deportivos.
- CLI `sports-capture`, documentación operativa, ZIP reproducible por allowlist y
  CI ampliado para JS/UI/paquete sin secretos ni artifacts de datos.

## Archivos creados

- `.node-version`.
- `extension/manifest.json`, `background.js`, `core.mjs`, `picker.mjs`,
  `panel.html`, `panel.css`, `panel.mjs`, `README.md`.
- `src/sports_analysis/providers/browser.py`, `db/browser.py`, `browser_cli.py`.
- `migrations/0005_browser_capture.sql`, `0006_browser_review_audit.sql`.
- `scripts/package_extension.py`.
- `tests/__init__.py`, `tests/browser_fixtures.py`, `tests/unit/__init__.py`,
  `tests/unit/test_browser.py`, `tests/integration/test_browser.py`,
  `tests/extension/__init__.py`, `tests/extension/core.test.mjs`,
  `tests/extension/test_browser_ui.py`.
- `docs/BROWSER_CAPTURE.md`, `docs/decisions/0007-browser-capture-provider.md`
  y este informe.

Los paths abreviados dentro de cada línea comparten su directorio. El ZIP y una
vista de la UI con datos sintéticos se generan en `.local/` y no pertenecen a Git.

## Archivos modificados

`README.md`, `AGENTS.md`, `.gitignore`, `.github/workflows/ci.yml`, `pyproject.toml`,
`uv.lock`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `POINT_IN_TIME.md`, `SECURITY.md`,
`DEVELOPMENT.md`, `docs/PROJECT_SPEC.md`, `docs/IMPLEMENTATION_STATUS.md`,
`scripts/check_public_repository.py`, `tests/integration/test_database.py` y
`tests/unit/test_repository_security.py`.

Al cerrar la iteración, los cambios estaban locales; su publicación posterior fue
autorizada por el usuario y queda registrada en el historial de Git. Se conserva
el trabajo anterior y ninguna migración ya aplicada fue reescrita.

## Migraciones

0005 agrega recibos de capturas, observaciones inmutables y comandos de tracking;
0006 vincula observaciones a revisión pública y protege el ledger de comandos.
Hay **50 tablas de dominio**, además de la tabla técnica de migraciones, en los
nueve schemas existentes. No se concede acceso nuevo al schema privado.

Aplicadas en PostgreSQL 16 desechable, junto con las cuatro anteriores. La suite
valida instalación desde cero, integridad, permisos e importaciones concurrentes.
Dos ejecuciones posteriores del migrador aplicaron cero cambios. No se migró Neon.

## Pruebas y resultados

| Check | Resultado |
| --- | --- |
| `uv sync --frozen` | Aprobado |
| `pytest` completo | **229 aprobadas**, sin skips: 174 unitarias, 48 PostgreSQL, 7 UI/DOM |
| `node --test tests/extension/*.test.mjs` | **6 aprobadas** |
| `ruff check` / `ruff format --check` | Aprobados |
| `mypy` estricto | Aprobado, 21 archivos fuente |
| Sintaxis JS/MJS (`node --check`) | Aprobada |
| `actionlint 1.7.7` | Aprobado; CI remoto todavía no ejecutado |
| `pip-audit` | Sin vulnerabilidades conocidas; proyecto editable excluido como paquete propio |
| `uv build` | Wheel y sdist generados e inspeccionados |
| ZIP de extensión | 8 assets, integridad y reproducibilidad comprobadas |
| Scanner público / `git diff --check` | Aprobados |
| HTML original | SHA-256 idéntico al inicial; fuera de Git y paquetes |

Se añadieron **48 casos pytest** y **6 casos Node** frente al cierre de Foundation.
Incluyen filtros de privacidad, campos/fechas/cuotas inválidos, mercados completos,
PIT de recepción/reproceso, hashes/idempotencia, fallos de escritura y reintentos,
concurrencia real, roles SQL, mapping ambiguo, ciclos terminales y seguimiento.
La UI prueba descarga que el parser Python acepta, invalidación al editar/navegar,
selector sin ejecutar el botón original, rechazo de boletas/formularios y Escape.

## Límites de la validación y problemas resueltos

El navegador cloud prohíbe administrativamente cargar extensiones descomprimidas;
la llamada de carga fue rechazada. **No se ha verificado instalación real de MV3,
toolbar, concesión activeTab ni sidePanel.** Las pruebas usan Chromium real para
DOM/UI/descargas, sirven los assets bajo su CSP y simulan las APIs Chrome.
La aceptación real se completa en Chrome/Edge local siguiendo la guía.

La descarga oficial del navegador de Playwright recibió 403 de la política de
red. Se utilizó el Chromium 151 instalado; no se deshabilitó TLS ni se cambió la
política del navegador. Playwright está fijado en el lockfile. CI dispone de un
paso de instalación oficial, cuya ejecución remota sigue sin comprobarse.

Las pruebas detectaron y corrigieron una colisión entre el ID del aviso de UI y
el campo de estado del partido. También se corrigió el empaquetado de los módulos
de tests para que la suite unitaria funcione por separado, como indica el README.
No quedan fallos conocidos en los checks ejecutados.

## Decisiones arquitectónicas

ADR 0007 documenta panel junto a pestaña, acceso temporal, exportación explícita,
calidad MANUAL_UNVERIFIED, reloj confiable al recibir y recepción duradera antes
de objetos. Una revisión posterior no se vuelve disponible retrospectivamente.
No se adivinan mappings ni temporada; las identidades deben confirmarse.

Las escrituras manuales cortas usan advisory lock transaccional con timeout;
los análisis largos futuros conservan los locks TTL/fencing Foundation. El
snapshot tracking no es una fuente histórica para backtests. Las cuotas RAW no
activan paper, modelos ni el cálculo de value. El worker público sigue sin acceso
privado. No se añaden cron que pretendan controlar una pestaña local del usuario.

## Configuración y deuda pendientes

El entorno actual dispone de Python/uv/Node, Chromium y PostgreSQL desechable.
Se guardaron `install_script` y `start_skill` actualizados en el borrador cloud,
con comandos probados, uso del checkout existente y arranque/readiness de DB.
El borrador **requiere revisión, guardado y publicación desde la configuración
del entorno**; guardarlo no publica ni prueba restauración en una tarea nueva.

La extensión no requiere secretos. El importador necesita DATABASE_URL de runtime
y almacenamiento local persistente; credenciales de migración se administran por
separado. Aún faltan aprovisionamiento/configuración de Neon y R2, endpoint/bucket
y credenciales de objetos con permisos mínimos, y autorización/documentación de
una fuente automática si se quiere cron. No se pidieron ni inventaron esos valores.

No se validó ninguna página real de SofaScore/Betano ni compatibilidad de sus DOM.
El selector es genérico y manual; no certifica que todos los campos provengan de
una misma actualización. No cruza iframes. Los filtros no sustituyen la revisión
de datos públicos. Tampoco existen envío remoto, almacenamiento de perfiles de
selectores, catálogos de temporadas, resolución auditada de identidades confirmadas
ni un scheduler que actualice automáticamente un ACTIVE obsoleto.

## Siguiente incremento exacto y requisitos no perdidos

1. Aceptar la instalación y una captura autorizada real en Chrome/Edge local;
   validar el contrato importando ese JSON sin publicar datos de cuenta.
2. Completar temporadas y resolución auditada de conflictos/correspondencias,
   conservando vigencia temporal y sin reparentar historia.
3. Configurar Neon/R2 y una fuente ejecutable en servidor o recepción autenticada
   de capturas; nunca poner esas credenciales en la extensión.
4. Definir cadencias y ejecutar `refresh_calendar`/`tracking_scheduler` con locks,
   slots, reintentos y recuperación tras inactividad, sin fabricar observaciones.
5. Cerrar Fase 2 antes de normalización operativa de odds, Parquet, benchmarks y
   selector en Fase 3.

Continúan pendientes según la especificación: fuentes de estadísticas, noticias,
lesiones, alineaciones y clima; R2/Parquet/datasets; motor estadístico fútbol →
básquet → béisbol; officialización y liquidación/CLV; precio paper y umbrales NO BET
prospectivos; métricas log-loss/calibración/CLV/ROI; GBM y luego redes con evaluación
fuera de muestra; holdout administrativo; frontend Pages/historial público;
repositorio privado, tokens y apuestas reales. Nada de esto se declara implementado
por aparecer en el schema o la documentación. La matriz y PROJECT_SPEC conservan
los criterios para las próximas iteraciones.
