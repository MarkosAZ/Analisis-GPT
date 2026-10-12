# Iteración 05 — Escáner de navegador con conectores incluidos

## Proyecto y punto de partida

Sistema deportivo prepartido auditable: RAW → NORMALIZED → FEATURES → PREDICTIONS,
PIT, ciclos históricos y separación entre predicciones, paper y apuestas privadas.
Foundation estaba cerrada; Fase 2 parcial. Ya existían importador, calendario,
tracking, web estática y extensión 0.3 con cola automática y perfiles DOM.
Faltaban lectores incluidos: activar el motor requería escribir perfiles JSON.

El usuario aportó [Analisis-BDP, commit 7b0dcd97](https://github.com/LuisP11127/Analisis-BDP/tree/7b0dcd97b4db471057508ba47df04b0bb0d4ccaa/extension)
como ejemplo de escáner desde su navegador. Se inspeccionaron controlador,
manifest, puente, diagnóstico, red y formatos de los cuatro conectores relevantes.
No se ejecutó el código externo ni se incorporaron sus hooks o gestión de tokens.

## Implementación

- Extensión 0.4 con configuración por casillas y concesión de permisos por fuente.
  Los perfiles DOM avanzados y la captura manual siguen disponibles.
- SofaScore/Flashscore: calendario de fútbol de hoy según Lima, IDs estables,
  conservación de aplazados/cancelados y rechazo de datos incompletos.
- Betano: proyección acotada del estado público de la página de fútbol; mercados
  completos 1X2, ambos anotan y totales con formato reconocido.
- Apuesta Total: snapshot y petición ML0/OU0 para hasta diez eventos. Usa únicamente
  destinos públicos fijos y la sesión que el navegador envía al sportsbook;
  no lee cookies ni fuerza login/logout. Una denegación termina esa fuente.
- Preview en la web y diagnóstico descargable por fuente, incluso sin capturas;
  errores sanitizados, versión del lector y contadores de registros omitidos.
- Capturas v3/AUTOMATIC_SOURCE, normalizador v3 y SOURCE_UNVERIFIED. Se validan
  origen, tipo, deporte y versión; los contratos y manifests v1/v2 se conservan.
- Cancelación aborta peticiones pendientes. Se admiten redirecciones iniciales
  de idioma acotadas y no se cierran pestañas con navegación del usuario pendiente.
- ZIP por lista fija de 19 assets y documentación permanente actualizada.

## Validación

| Comprobación | Resultado |
| --- | --- |
| Pytest completo, PostgreSQL incluido | 292 aprobados, sin omitidos |
| Node, extensión y web | 37 aprobados |
| Nuevos casos Python | 15: 13 de contrato v3, 1 SQL y 1 UI/DOM; ampliaciones a pruebas existentes |
| Nuevos casos JavaScript | 12: conectores/red, cola y cierre seguro |
| Ruff lint y formato | Aprobados |
| Mypy estricto | Aprobado, 23 archivos de fuente |
| Actionlint | Aprobado; workflows sin cambios |
| Pip-audit | Sin vulnerabilidades conocidas; proyecto editable excluido |
| Wheel/sdist y build estático | Aprobados |
| Web ejecutada | HTTP 200, calendario válido y ZIP 0.4 con 19 assets |
| Chromium | Configuración por casillas, preview, diagnóstico, proyección pública y contrato JS→Python; sin errores JS ni overflow en escritorio/móvil |

Los tests de conectores usan respuestas y estados sintéticos. Las APIs Chrome se
simulan: la política administrada del cloud impide instalar MV3 descomprimido.
No se declara aceptación de sitios reales ni cuotas reales verificadas. El uso
normal de la extensión no requiere publicar cambios de red del entorno cloud.

## Migraciones, decisiones y problemas

**Sin migraciones nuevas, dependencias nuevas ni cambios en producción.** Las seis
migraciones existentes y los permisos se ejercitaron sobre PostgreSQL desechable.
SQL sigue fijando available_at al recibir datos; importar más tarde no permite
introducirlos retrospectivamente. Cuotas siguen RAW_ONLY, sin apuestas ni modelos.

ADR 0010 adapta el funcionamiento de la referencia manteniendo las restricciones
del proyecto. Se sustituyen captura general de tráfico/encabezados, respuestas
completas, tokens GitHub, reintentos ante denegación y enumeración de mercados por
conectores acotados. Las etiquetas deportivas no reconocidas no se adivinan;
contradicciones del mismo mercado se reportan. No se cambia line_selector_v1.

Se corrigieron las comprobaciones anteriores de CSP para validar los tres hosts
API permitidos, preservando el aislamiento de Pages. Se ajustó el test del editor
avanzado, ahora plegado, y el formato de un test Python. Los checks finales pasan.

## Pendientes y siguiente fase exacta

1. Instalar/recargar el ZIP 0.4 en Chrome/Edge local, activar fuentes y ejecutar un
   escaneo. Verificar precios, IDs, estados, cancelación, suspensión del worker,
   permisos y exportación/importación. Usar el diagnóstico local para investigar
   respuestas denegadas o cambios de formato; no eludir controles de las fuentes.
2. **Te Apuesto no tiene lector.** Tampoco figura en la referencia. Requiere
   inspección autorizada de su formato antes de implementarlo.
3. Ampliar solo con evidencia: navegación por cada evento de Betano, más mercados,
   básquet/béisbol y fuentes de noticias/estadísticas/clima. El incremento actual
   no promete todos los datos o capacidades del otro proyecto.
4. Cerrar Fase 2: temporadas, conflictos de correspondencias, fuente/recepción
   remota, Neon/R2 y workflows operativos. Después vienen odds/Parquet, modelos,
   paper, evaluación y ML según PROJECT_SPEC.md; no se activaron prematuramente.

La extensión no necesita secretos nuevos. PostgreSQL/object storage siguen
configurándose fuera del navegador para importar. La recepción remota, Neon/R2,
credenciales de producción y publicación automática de nuevos calendarios siguen
pendientes. El HTML original continúa excluido del repositorio y del paquete.

## Inventario

Archivos nuevos: `extension/connectors.mjs`, `extension/source-page.mjs`,
`extension/source-parsers.mjs`, `tests/extension/connectors.test.mjs`,
`tests/unit/test_source_browser.py`, `docs/decisions/0010-browser-source-connectors.md`
y este informe.

Archivos modificados: `AGENTS.md`, `ARCHITECTURE.md`, `DEVELOPMENT.md`, `README.md`,
`SECURITY.md`, `docs/AUTOMATIC_SCANNING.md`, `docs/BROWSER_CAPTURE.md`,
`docs/IMPLEMENTATION_STATUS.md`, `docs/PROJECT_SPEC.md`, `docs/WEB.md`,
`extension/README.md`, `extension/background.js`, `extension/bridge.js`,
`extension/manifest.json`, `extension/scan-contract.mjs`, `extension/scan.css`,
`extension/scan.html`, `extension/scan.mjs`, `extension/scanner.mjs`, `index.html`,
`scripts/package_extension.py`, `src/sports_analysis/db/browser.py`,
`src/sports_analysis/providers/browser.py`, `tests/browser_fixtures.py`,
`tests/extension/core.test.mjs`, `tests/extension/scanner.test.mjs`,
`tests/extension/test_automatic_ui.py`, `tests/integration/test_automatic_browser.py`,
`tests/web/test_site.py`, `web/scanner.mjs` y `web/styles.css`.
