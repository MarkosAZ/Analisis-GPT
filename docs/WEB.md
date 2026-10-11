# Web HTML del proyecto

`index.html` es una página propia del proyecto. El HTML de la conversación de
diseño permanece fuera del sitio, de Git y de todos los paquetes.

## Ejecutar desde el repositorio

```bash
uv sync --frozen
uv run python scripts/serve_site.py --port 8000
```

El proceso construye un directorio temporal con los assets permitidos y lo sirve
por HTTP en loopback. Detén con Ctrl+C y reinicia después de modificar archivos.
No sirve la raíz del checkout ni ofrece listado de directorios. Abrir el HTML
directamente con `file://` no funciona porque usa módulos y JSON por HTTP.

La página permite consultar Partidos, Seguimiento e Historial, buscar equipos y
competición, filtrar por deporte/Hoy/Mañana y abrir el detalle de un ciclo. Todas
las fechas se muestran en America/Lima. Partidos usa el ciclo más reciente de
cada evento; Historial conserva los anteriores. La sección Extensión ofrece una
guía y un ZIP generado exclusivamente con sus assets.

El calendario publicado empieza vacío. **Explorar ejemplo** carga cinco eventos
ficticios, incluyendo un aplazamiento con dos ciclos, con aviso visible. No son
capturas reales ni predicciones. No hay modelos, ROI, recomendaciones ni apuestas.

## Mostrar un calendario público

Configura `DATABASE_URL` en el entorno del importador, fuera de Git. Usa un login
con los privilegios de `sports_public_worker`, nunca credenciales del esquema
privado. Tras importar y resolver capturas siguiendo [BROWSER_CAPTURE.md](BROWSER_CAPTURE.md):

```bash
mkdir -p .local
uv run sports-capture export-calendar .local/calendar.json
uv run python scripts/serve_site.py --port 8000 --snapshot .local/calendar.json
```

El exportador rechaza sobrescribir archivos existentes. También puedes abrir ese
JSON con **Cargar calendario** en la web: se valida en memoria y no se sube, guarda
en localStorage ni envía al backend. Las capturas `browser_capture_v1` y el archivo
`tracking_v1` tienen otro contrato y no se admiten como calendario público.

`public_calendar_v1` contiene únicamente versión, tipo PUBLIC/SYNTHETIC, fecha de
generación, zona de visualización y ciclos. Cada ciclo conserva UUID de evento y
ciclo, predecesor, número, deporte, competición, equipos, fechas y estados. No
contiene RAW, URLs de origen, cuotas, stakes ni datos privados. Se rechazan campos
extra, más de 2 MiB, más de 5000 ciclos, fechas inválidas, UUID duplicados,
predecesores inconsistentes y observaciones posteriores a la generación.

El JSON es una fotografía del estado actual. `last_observed_at` identifica la
disponibilidad de la última captura aplicada vinculada al ciclo; no fecha todas
las transiciones. El historial visual no es un dataset de backtest `as_of`.
El tracking mostrado es de solo lectura; se cambia mediante el CLI autorizado,
y una publicación puede quedar obsoleta si no se actualiza el calendario.

## Construir y publicar

```bash
uv run python scripts/build_site.py --output .local/pages
```

Para construir con datos exportados, añade `--snapshot .local/calendar.json`.
El destino debe ser nuevo. El build valida el JSON y copia solo HTML, CSS, JS,
icono, calendario, ejemplo sintético, `.nojekyll` y el ZIP de la extensión.
Nunca publiques el checkout entero.

El workflow **Publish public HTML** (`.github/workflows/pages.yml`) construye el
sitio en cada push a main y por ejecución manual. El build usa `web/public.json`,
actualmente vacío. Para actualizar los datos públicos de ese workflow, revisa
deliberadamente el export y reemplaza únicamente `web/public.json` por un
snapshot PUBLIC validado. No subas capturas RAW ni el directorio `.local`.
La exportación automática desde Neon/R2 sigue pendiente.

Un administrador debe configurar una vez **Settings → Pages → Build and deployment
→ Source: GitHub Actions** si todavía no está activo. Después puede ejecutar
**Actions → Publish public HTML → Run workflow** en main. El workflow no necesita
un PAT ni secretos de base de datos; el GITHUB_TOKEN ordinario no puede habilitar
por sí solo un sitio Pages sin configurar.

Dirección prevista: `https://markosaz.github.io/Analisis-GPT/`. Confirma el enlace
real y el éxito en el environment `github-pages`. El [primer workflow remoto](https://github.com/MarkosAZ/Analisis-GPT/actions/runs/38103689223)
construyó el sitio y generó el artifact, pero `configure-pages` falló con **Not Found**:
el sitio debe estar habilitado y configurado para GitHub Actions. Completa el paso
administrativo anterior y vuelve a ejecutar el workflow.

La página pública de Actions permitió comprobar ese resultado. La red del cloud
rechazó con HTTP 403 tanto `api.github.com` como el dominio del sitio, de modo que
no se pudo configurar Pages ni abrir su dirección desde esta sesión. La ejecución
HTTP y las pruebas locales de la web sí se completaron.

## Validación y límites

```bash
uv run pytest tests/web
node --test tests/web/*.test.mjs
```

Las pruebas usan Chromium real en escritorio/móvil para filtros, navegación,
detalle de ciclos, archivos inválidos, ausencia de subida y descarga de extensión.
La integración PostgreSQL prueba el export con el rol público y una reprogramación.
Los assets usan una CSP de recursos propios y textos mediante `textContent`.

La sección privada, trazabilidad de predicciones, dashboards de evaluación,
datasets y laboratorio siguen pendientes. Este incremento no cierra Fase 2 ni
Fase 7; respeta los contratos necesarios para continuar ambas.
