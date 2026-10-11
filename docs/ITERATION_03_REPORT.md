# Iteración 03 — Web HTML ejecutable

## Proyecto y punto de partida

Sistema prepartido de fútbol, básquet y béisbol con datos reproducibles,
predicciones auditables, evaluación prospectiva y separación de apuestas reales.
Foundation estaba cerrada. Fase 2 tenía extensión manual, RAW inmutable,
normalización, mappings, ciclos y tracking local, pero no una página ejecutable.
El usuario pidió añadirla y había autorizado subir el trabajo a GitHub.

## Implementación

- HTML estático propio con vistas Partidos, Seguimiento, Historial y Extensión.
- Filtros de deporte/búsqueda/Hoy/Mañana con zona America/Lima; detalle de ciclos
  y reprogramaciones, sin colapsar el historial del evento.
- Calendario vacío por defecto; ejemplo explícito de cinco eventos ficticios.
- Exportación SQL de solo lectura `sports-capture export-calendar`, contrato
  `public_calendar_v1` y validación Python/JS de campos, fechas e identidades.
- Carga local de JSON en memoria, sin subida ni persistencia en el navegador.
- Build por lista explícita, ZIP de extensión y servidor HTTP aislado del checkout.
- Workflow Pages fijado por SHA, push/manual en main no fork, permisos de escritura
  exclusivos del despliegue; CI añade pruebas JS y construcción de la web.

No se añadieron dependencias ni migraciones. Se conservaron las seis migraciones
y los permisos existentes. No se ejecutó DDL en Neon ni en producción.

## Inventario

Archivos nuevos:

- `index.html`; `web/app.mjs`, `web/core.mjs`, `web/styles.css`, `web/icon.svg`,
  `web/public.json` y `web/demo.json`.
- `src/sports_analysis/public_calendar.py` y `db/public_calendar.py` dentro del
  mismo paquete; `scripts/build_site.py` y `scripts/serve_site.py`.
- `.github/workflows/pages.yml`.
- `tests/web/{__init__.py,core.test.mjs,test_publication.py,test_site.py}` y
  `tests/integration/test_public_calendar.py`.
- `docs/WEB.md`, ADR 0008 y este informe.

Archivos modificados:

- `src/sports_analysis/browser_cli.py`, `.github/workflows/ci.yml` y
  `tests/unit/test_repository_security.py`.
- `AGENTS.md`, `README.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `DEVELOPMENT.md`,
  `SECURITY.md`, `docs/BROWSER_CAPTURE.md`, `docs/PROJECT_SPEC.md` y
  `docs/IMPLEMENTATION_STATUS.md`.

## Evidencia de validación

| Comprobación | Resultado local |
| --- | --- |
| Suite Python completa con PostgreSQL 16 | **249 aprobados, 0 omitidos** |
| Nuevos tests Python | 20: 12 contrato/build, 7 web Chromium y 1 integración SQL |
| Tests JavaScript | **11 aprobados**, incluidos 5 nuevos de calendario |
| Ruff lint y formato | Aprobados, 76 archivos Python formateados |
| Mypy estricto | Aprobado, 23 archivos de fuente |
| Actionlint 1.7.7 | Ambos workflows válidos |
| Pip-audit | Sin vulnerabilidades conocidas; paquete propio editable excluido |
| Build Python | Wheel/sdist construidos e inspeccionados para excluir material privado |
| Build estático | Directorio público generado, contrato y lista de assets comprobados |
| Build remoto Pages | Aprobado; artifact generado por GitHub Actions |
| Deploy remoto Pages | Falló: `configure-pages` devolvió Not Found; requiere habilitar/configurar Pages |
| Repositorio público | 108 archivos comprobados; sin HTML de contexto ni credenciales detectadas |
| Arranque HTTP | Servidor activo; HTML y calendario devuelven 200 y contrato válido |
| CLI público | Exportación real contra PostgreSQL desechable validada |
| Navegador | Escritorio y móvil, navegación, filtros, ciclos, errores y descarga ZIP |

La suite SQL también verifica migraciones, permisos, idempotencia, locks,
temporalidad y gobernanza anteriores. Las pruebas web usan Chromium real; las de
extensión conservan su límite de APIs Chrome simuladas, porque la política del
navegador cloud impide instalar extensiones descomprimidas. Las capturas visuales
de desarrollo permanecen en `.local`, fuera de Git y artifacts.

Se actualizó y guardó `start_skill` del entorno con el servidor y comprobación
HTTP, preservando el arranque PostgreSQL. El guardado es un borrador: requiere
revisión/guardado y publicación del entorno en su configuración para futuras
tareas; no demuestra restauración en una instancia nueva.

## Decisiones y problemas

ADR 0008 permite adelantar la presentación del calendario por petición explícita,
sin declarar completas Fase 2 ni Fase 7. El HTML original de contexto se conserva
localmente y nunca se publica. La exportación de estado actual no sustituye
`as_of(decision_time)`; `last_observed_at` es una captura vinculada, no el momento
de todas las transiciones. No se añadieron reglas retroactivas ni políticas activas.

Se alineó el formato de timestamps Python con el aceptado por el navegador para
evitar publicar archivos válidos en el builder que la interfaz rechazaría.
Las validaciones rechazan en vez de truncar snapshots que superen 5000 ciclos o
2 MiB; la paginación será necesaria si el historial supera esos límites.

La red del cloud respondió HTTP 403 para `api.github.com` y `markosaz.github.io`.
Git HTTPS y la página pública de Actions sí están disponibles. El [workflow remoto](https://github.com/MarkosAZ/Analisis-GPT/actions/runs/38103689223)
del commit `e76ea6c` construyó el artifact y falló al desplegar: `configure-pages`
devolvió Not Found y pidió habilitar Pages con Source: GitHub Actions. El sitio
todavía no está publicado. No se necesita agregar un PAT; un administrador puede
completar la configuración desde GitHub y repetir la ejecución.

GitHub también avisó de Actions con runtime Node 20 forzado a Node 24. El build
remoto funcionó; actualizar esas versiones oficiales fijadas queda como
mantenimiento pendiente, separado del bloqueo de configuración de Pages.

## Pendiente y siguiente fase

Primero habilitar Pages en GitHub con Source: GitHub Actions y repetir el despliegue.
Después cerrar Fase 2: aceptación de captura autorizada real, temporadas,
resolución auditada de conflictos, persistencia Neon/R2 y fuente ejecutable en
servidor o recepción autenticada; entonces añadir refresh/scheduler con slots,
locks y recuperación tras inactividad. La publicación de snapshots todavía es
deliberada/manual, sin generación automática desde una base remota.

Neon, R2 y fuentes deportivas requerirán sus credenciales con permisos mínimos
en la fase operativa; ninguna es necesaria para esta web y no se pidió ni creó
ningún secreto nuevo. No exponer esas credenciales al frontend ni a PRs/forks.

Continúan pendientes las cuotas normalizadas/Parquet, datos deportivos/contexto
reales, features y modelos, datasets y backtesting, paper/NO BET activados
prospectivamente, liquidación y evaluación, registro de modelos operativo,
holdout administrativo, dashboards de análisis/laboratorio, alertas y repositorio
privado. La lista detallada permanece en [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)
y las decisiones abiertas en [PROJECT_SPEC.md](PROJECT_SPEC.md).
