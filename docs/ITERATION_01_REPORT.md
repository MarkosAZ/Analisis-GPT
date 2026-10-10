# Iteración 01 — Foundation

## Proyecto reconstruido y fase

Sistema prepartido para fútbol, básquet y béisbol: probabilidades auditables,
comparación con mercado sin vig, historial prospectivo y paper betting separado
de apuestas reales. Actions ejecutará jobs; Neon/PostgreSQL conservará datos
estructurados, R2 los objetos grandes y Pages consumirá JSON estático.

El HTML completo fue parseado; contenía cuatro turnos usuario/asistente y
referencias a acuerdos anteriores no incluidos como mensajes. Se leyeron todos
los mensajes extraídos y se distinguieron UI/configuración de contenido. No se
reproduce metadata privada ni se inventa el historial faltante. La última decisión
vigente limita la iteración a **Fase 1 — Foundation**.

El repositorio inicial tenía únicamente `README.md` con un título. No había código,
workflows, tests, migraciones o frontend que preservar o corregir. Toda la
fundación estaba pendiente. No se inició automáticamente Fase 2.

## Implementación

- Paquete Python 3.12, dependencias bloqueadas con uv, configuración sin valores
  secretos y CLI de migraciones transaccionales con checksums.
- Nueve schemas PostgreSQL, **47 tablas de dominio** y una tabla técnica. UUID,
  PK/FK, constraints, índices de idempotencia, procedencia y probabilidades.
- Roles públicos, de entrenamiento y privados separados; permisos por defecto;
  ventanas/etiquetas de holdout protegidas mediante RLS y controles administrativos.
- Dominio tipado: `as_of`, revisiones, payloads inmutables, ciclos, aplazamientos,
  estados de run, idempotencia, TTL, registry y vigencia prospectiva.
- Adquisición concurrente de locks en PostgreSQL con fencing y comprobación
  transaccional de propietario; reconciliación de timeout como regla de dominio.
- Cuatro protocolos de providers, fixtures offline, normalizador y recorrido
  RAW → NORMALIZED → as_of. No endpoints reales ni scraping.
- Object store local POSIX: publicación atómica, hashes, protección de rutas,
  symlinks y archivos especiales; observaciones repetidas conservadas; manifests.
- Two/three-way, de-vig proporcional, edge, favored/value y elegibilidad v1;
  reconocimiento de enteras/asiáticas sin seleccionarlas.
- Paper de una unidad con fuente explícita, máximo edge positivo, vigencia
  prospectiva, motivos NO BET y rechazo de datos futuros/no comparables.
  Configuraciones reales permanecen DRAFT, sin activar thresholds ni fuente de precio.
- CI sin secretos de producción ni artifacts, Actions fijadas por SHA y PostgreSQL
  por digest. Contexto permanente, ADRs y guía para agentes.

## Migraciones ejecutadas

| Archivo | Responsabilidad |
| --- | --- |
| `0001_foundation.sql` | Nueve schemas, tablas, semillas e invariantes base |
| `0002_permissions.sql` | Roles, permisos, holdout, modelos y registros inmutables |
| `0003_historical_integrity.sql` | Vectores completos, vínculos y vigencia de paper/modelos, RLS de evaluación y locks |
| `0004_quote_and_evaluation_guards.sql` | Matemática del de-vig, tiempos de snapshots y protección de etiquetas por ciclo |

Se aplicaron en PostgreSQL 16 local, también desde cero en una base desechable
nueva. Repetirlas aplica cero cambios; alterar el checksum se rechaza. No se
migró Neon ni otra base de producción. No hay downgrade destructivo automático.

## Pruebas y verificaciones

**181 aprobadas: 149 unitarias y 32 de integración. Ninguna omitida en la ejecución
completa.** Las pruebas cubren todos los invariantes mínimos de Foundation y casos
adicionales de integridad de metadata, mutabilidad, permisos efectivos, vectores
incompletos, precios, procedencia y concurrencia.

| Comprobación ejecutada | Resultado |
| --- | --- |
| `uv sync --frozen` | Instalación repetible correcta |
| `pytest` con PostgreSQL desechable | 181 passed |
| `ruff check .` | Aprobado |
| `ruff format --check .` | Aprobado |
| `mypy` estricto | Aprobado, 18 archivos de código |
| `pip-audit --skip-editable` | Sin vulnerabilidades conocidas en dependencias auditadas |
| `actionlint 1.7.7` | Workflow válido; release oficial verificado por SHA-256 |
| Comprobador del repositorio público | Aprobado |
| `uv build` | Wheel y sdist generados |
| Inspección de paquetes y hash del HTML | HTML/adjuntos/configuración local excluidos; original intacto |
| `git diff --check` | Aprobado |
| Frontend | No aplica: aún no existe |
| Actions remoto | No ejecutado; workflow y sus checks se validaron localmente |

## Decisiones y correcciones

1. Se conserva la separación por fases y el esquema consolidado. Las 47 tablas
   resultan de contar la lista completa; la cifra inicial 45 fue corregida.
2. Las apuestas reales nunca pasan por Actions públicos. El esquema privado es
   inaccesible al worker público incluso mediante SQL directo.
3. Se interpreta la regla final del selector como half-lines numéricas más
   mercados sin línea y sin push; nunca se finge que moneyline es una half-line.
4. Fuente de precio paper y thresholds NO BET siguen pendientes; no se inventa
   una estrategia activa. Mapping 0.99 es una decisión técnica versionada de
   Foundation, pendiente de validación con un proveedor real.
5. `paper_bets.placed_at` es el momento simulado original. El ledger oficial puede
   escribirse al officializar usando las políticas y precios de esa decisión;
   no recibe una política que empezó después.
6. El holdout se protege también frente a intervalos renombrados/solapados y
   accesos a resultados por rutas distintas. Su extensión a datasets/R2 queda
   explícitamente para esas integraciones.
7. Se corrigieron sintaxis SQL interrumpida, comprobaciones de roles con sesión
   superuser, mutabilidad temporal, validación de benchmarks y errores de tipado.
8. La auditoría detectó una vulnerabilidad de pytest 8.4.2; se actualizó a 9.1.1
   y se repitieron auditoría y tests. No se deshabilitó la verificación.

## Pendientes y deuda técnica explícita

La matriz completa está en `IMPLEMENTATION_STATUS.md`. No existen todavía
providers reales, calendario/tracking operativo, R2/Parquet/datasets, features
específicas, modelos estadísticos, GBM/redes, backtesting, métricas reales,
liquidación deportiva, workflow reconciliador ni frontend/Pages.

Antes de uso operativo: definir reglas de officialización/cierre/abandonos,
precio paper, thresholds y priorización de líneas; implementar repositorios de
persistencia que llamen `ops.assert_event_lock` en la transacción de salida;
versionar revisiones de resultados desde RAW; y asegurar los permisos de objetos
históricos/datasets en R2. Los helpers y el esquema no equivalen a un pipeline
productivo conectado. El administrador de la base y el propietario del filesystem
son autoridades de confianza, no identidades de runtime.

## Configuración futura y entorno cloud

Foundation funciona sin secretos externos. En fases posteriores harán falta
credenciales PostgreSQL separadas para migraciones y cada worker, acceso R2
(endpoint/bucket y claves acotadas), y autorización/configuración de las fuentes
seleccionadas. Los futuros tokens GitHub públicos/privados se definen en
`SECURITY.md`; no se solicitan ni guardan valores en este repositorio.

Se guardaron `install_script` y `start_skill` en el borrador del entorno cloud.
El guardado no publica ni aplica una versión nueva: revisar y guardar en ajustes
del entorno y después publicar es un paso del producto para reutilizar el snapshot.
No se ha comprobado restauración en una tarea nueva ni publicación remota.

## Siguiente fase exacta

**Fase 2 — Calendario + providers + tracking** en una nueva iteración:
seleccionar una fuente autorizada; implementar adapter y fixtures; persistir RAW
antes de normalizar; resolver identidades y revisiones; guardar eventos/ciclos
idempotentemente; habilitar selección/seguimiento y `tracking.json`; incorporar
`refresh_calendar`/`tracking_scheduler` seguros con recuperación de slots perdidos.
Probar reprogramaciones, cancelaciones, fallos, duplicados y disponibilidad temporal.
No añadir predicciones, entrenamiento avanzado ni apuestas reales en esa fase.

## Archivos modificados

- `README.md`: propósito, alcance, estructura y acceso a documentación.

## Archivos creados

- `.env.example`
- `.github/workflows/ci.yml`
- `.gitignore`
- `.python-version`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `DATA_MODEL.md`
- `DEVELOPMENT.md`
- `MODEL_GOVERNANCE.md`
- `POINT_IN_TIME.md`
- `SECURITY.md`
- `config/no_bet_policy_v1.json`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/ITERATION_01_REPORT.md`
- `docs/PROJECT_SPEC.md`
- `docs/decisions/0001-modular-foundation-and-phases.md`
- `docs/decisions/0002-public-private-boundary.md`
- `docs/decisions/0003-temporal-data-and-event-cycles.md`
- `docs/decisions/0004-line-selector-v1-and-pending-paper-policy.md`
- `docs/decisions/0005-prospective-governance-and-holdout.md`
- `docs/decisions/0006-persistence-and-foundation-boundaries.md`
- `migrations/0001_foundation.sql`
- `migrations/0002_permissions.sql`
- `migrations/0003_historical_integrity.sql`
- `migrations/0004_quote_and_evaluation_guards.sql`
- `pyproject.toml`
- `scripts/check_public_repository.py`
- `src/sports_analysis/__init__.py`
- `src/sports_analysis/config.py`
- `src/sports_analysis/db/__init__.py`
- `src/sports_analysis/db/migrate.py`
- `src/sports_analysis/domain/__init__.py`
- `src/sports_analysis/domain/events.py`
- `src/sports_analysis/domain/governance.py`
- `src/sports_analysis/domain/mappings.py`
- `src/sports_analysis/domain/markets.py`
- `src/sports_analysis/domain/paper.py`
- `src/sports_analysis/domain/runs.py`
- `src/sports_analysis/domain/temporal.py`
- `src/sports_analysis/providers/__init__.py`
- `src/sports_analysis/providers/base.py`
- `src/sports_analysis/providers/fixtures.py`
- `src/sports_analysis/storage/__init__.py`
- `src/sports_analysis/storage/objects.py`
- `src/sports_analysis/storage/raw.py`
- `tests/integration/__init__.py`
- `tests/integration/conftest.py`
- `tests/integration/test_database.py`
- `tests/integration/test_integrity.py`
- `tests/unit/test_config.py`
- `tests/unit/test_events.py`
- `tests/unit/test_governance.py`
- `tests/unit/test_mappings.py`
- `tests/unit/test_markets.py`
- `tests/unit/test_paper.py`
- `tests/unit/test_providers.py`
- `tests/unit/test_repository_security.py`
- `tests/unit/test_runs.py`
- `tests/unit/test_storage.py`
- `tests/unit/test_temporal.py`
- `uv.lock`
