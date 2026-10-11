# Iteración 04 — Automatización de la extensión

## Objetivo y estado

El proyecto sigue siendo un sistema deportivo prepartido auditable, con pipeline
RAW → NORMALIZED → FEATURES → PREDICTIONS y separación de apuestas privadas.
Foundation está cerrada; Fase 2 permanece parcial. Existían captura manual,
calendario/ciclos, tracking y web estática. El usuario pidió que la extensión
abriera y escaneara páginas automáticamente desde la web.

Se implementó el motor, pero **la extracción real de las cinco fuentes todavía
no está completada**. SofaScore, Betano Perú, Apuesta Total, Te Apuesto y Flashscore
Perú fueron rechazadas por la red cloud con 403 CONNECT antes de obtener HTML.
No se inventaron selectores ni se presentaron portadas abiertas como cuotas leídas.

## Cambios implementados

- Extensión 0.3: puente limitado a la web del proyecto, configuración local y
  permisos opcionales por host; no cookies, tráfico ni credenciales.
- Botones web para abrir las cinco fuentes, iniciar/cancelar un escaneo con
  perfiles válidos, consultar progreso y descargar capturas locales.
- Cola secuencial con lector DOM declarativo, límites, timeout, cancelación,
  recuperación explícita de interrupciones y cierre de pestañas propias.
- Perfiles con lector/ID/versión/hash; no ejecución de JavaScript desde perfiles.
- Capturas automáticas v2 y lote v1, diferenciados de la revisión manual.
- Importación CLI idempotente, recibo SQL confiable y manifests v2 con calidad
  DOM_UNVERIFIED. Capturas/manual manifests v1 compatibles e inmutables.
- Build y ZIP por lista explícita; nuevos archivos de datos/perfiles ignorados.

## Validación

| Comprobación | Resultado |
| --- | --- |
| Pytest completo, PostgreSQL 16 incluido | 277 aprobados, sin omitidos |
| Node | 25 aprobados |
| Tests nuevos Python | 28: 15 unitarios, 2 SQL, 9 UI/DOM de extensión, 2 UI web |
| Tests nuevos JavaScript | 14 de control/seguridad/perfiles, además de actualizar permisos |
| Ruff lint y formato | Aprobados |
| Mypy estricto | Aprobado, 23 archivos de fuente |
| Pip-audit | Sin vulnerabilidades conocidas; proyecto editable excluido |
| Actionlint | Workflows válidos; no se agregaron workflows |
| Build Python y sitio estático | Aprobados; ZIP 0.3.0 con assets explícitos |
| Web local real | HTTP 200, ZIP comprobado, escritorio/móvil sin errores JS ni overflow |

Las pruebas usan DOM y UI Chromium reales, con APIs Chrome simuladas; no prueban
instalación MV3 ni permisos en el navegador del usuario. La política administrada
impide cargar extensiones descomprimidas y no se eludió. Las fuentes reales no se
consultaron con éxito ni hay precios reales validados en esta iteración.

Se corrigieron una carrera de cancelación, el estado tras fallo de persistencia
y la pérdida del aviso de error al refrescar la interfaz. Un smoke de diagnóstico
que usaba eval quedó bloqueado por CSP: se verificó mediante locators, sin relajar
la política. El servidor anterior se reinició para servir los nuevos assets.

## Migraciones y decisiones

No se añadieron migraciones, dependencias ni secretos. Se probaron las seis
migraciones existentes y los permisos SQL. No hubo cambios en Neon/producción.
ADR 0009 sustituye el alcance exclusivamente manual de ADR 0007; conserva fases,
PIT, RAW previo a normalización y aislamiento privado. La automatización ocurre
localmente en el navegador; no convierte Pages en backend ni Actions en navegador.

El cliente no puede retroceder available_at. Los lotes conservan timestamps/UUID
por observación; un reintento reutiliza bytes y recibos. La revisión de identidades
sigue siendo explícita. Odds sigue RAW_ONLY, sin modificar line_selector_v1,
políticas paper/NO BET ni modelos. Capturar una lectura no acredita autenticidad.

## Configuración y pendientes

Se guardaron los cinco dominios exactos y las instrucciones de arranque actualizadas
en el borrador del entorno. No cambia la instancia actual: requiere revisión,
guardado y publicación desde la configuración del entorno. No se pidieron tokens.

Siguiente paso concreto: aplicar esa ampliación de red; inspeccionar páginas
públicas autorizadas; implementar y versionar lectores específicos con fixtures
saneados y navegación acotada entre eventos/mercados; contrastar datos reales;
probar instalación, permisos, suspensión, cancelación y exportación en Chrome/Edge.
Si un proveedor restringe automatización, obtener acceso autorizado o mantenerlo
sin lector. El motor no omite esa condición ni evade controles.

Después continúa el cierre de Fase 2: temporadas, resolución de conflictos,
Neon/R2, recepción/fuente de servidor y workflows operativos. Normalización de
odds/Parquet, modelos, paper, evaluación, ML y parte privada siguen pendientes,
como registra IMPLEMENTATION_STATUS.md. La publicación remota de Pages conserva
su requisito de habilitación en la configuración de GitHub.

## Archivos creados

- `docs/AUTOMATIC_SCANNING.md`
- `docs/ITERATION_04_REPORT.md`
- `docs/decisions/0009-automatic-browser-scanning.md`
- `extension/bridge.js`
- `extension/reader.mjs`
- `extension/scan-contract.mjs`
- `extension/scan.css`
- `extension/scan.html`
- `extension/scan.mjs`
- `extension/scanner.mjs`
- `extension/sources.mjs`
- `tests/extension/background.test.mjs`
- `tests/extension/scanner.test.mjs`
- `tests/extension/test_automatic_ui.py`
- `tests/integration/test_automatic_browser.py`
- `tests/unit/test_automatic_browser.py`
- `web/scanner.mjs`

## Archivos modificados

- `.gitignore`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `DEVELOPMENT.md`
- `README.md`
- `SECURITY.md`
- `docs/BROWSER_CAPTURE.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/PROJECT_SPEC.md`
- `docs/WEB.md`
- `extension/README.md`
- `extension/background.js`
- `extension/manifest.json`
- `extension/panel.html`
- `index.html`
- `scripts/build_site.py`
- `scripts/check_public_repository.py`
- `scripts/package_extension.py`
- `src/sports_analysis/browser_cli.py`
- `src/sports_analysis/db/browser.py`
- `src/sports_analysis/providers/browser.py`
- `tests/browser_fixtures.py`
- `tests/extension/core.test.mjs`
- `tests/web/test_site.py`
- `web/styles.css`
