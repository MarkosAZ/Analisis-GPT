# Desarrollo

## Requisitos y arranque

Python 3.12, `uv` (CI fija 0.12.19), Node 24.19.0, Chromium y PostgreSQL 16. Docker permite probar
sin Neon ni credenciales externas. Trabaja en el checkout existente; cada tarea
cloud ya está aislada y no necesita otro worktree.

Desde la raíz del repositorio:

```bash
uv sync --frozen
docker run --detach --rm --name sports-foundation-db \
  --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=sports_test \
  --publish 127.0.0.1:54329:5432 \
  postgres:16@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d
docker exec sports-foundation-db pg_isready -U postgres -d sports_test
export TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:54329/sports_test
uv run pytest
node --test tests/extension/*.test.mjs tests/web/*.test.mjs
```

Espera a que `pg_isready` confirme disponibilidad. Ese contenedor es una base
desechable de pruebas, ligada únicamente a loopback y sin datos reales. El modo
trust se limita a este entorno de pruebas. No sirve para producción. Si ya existe
el contenedor, reutilízalo cuando esté sano. Al terminar: `docker stop
sports-foundation-db` (solo el contenedor creado para estas pruebas).

La suite de integración requiere una base **desechable**, permisos de propietario
y creación de roles. Nunca apuntes `TEST_DATABASE_URL` a producción. Sin esta
variable los tests PostgreSQL se omiten explícitamente; no constituyen validación
completa. CI proporciona PostgreSQL y ejecuta esos tests.

## Migraciones

```bash
export DATABASE_URL=postgresql://postgres@127.0.0.1:54329/sports_test
uv run sports-db --directory migrations
uv run sports-db --directory migrations
```

El segundo comando debe aplicar cero migraciones. El runner verifica hashes de
migraciones ya aplicadas, serializa mediante advisory lock y ejecuta transacciones.
No edites una migración aplicada: añade una nueva. No hay downgrade destructivo
automático. En producción usa un propietario de migraciones separado; los workers
son roles de grupo sin login, y un administrador debe asignarles credenciales
distintas con privilegios mínimos. Ningún workflow de PR recibe esas credenciales.

La configuración lee el entorno; `.env.example` documenta nombres, pero `.env` no
se carga implícitamente. No incluyas una DSN como argumento de terminal ni la
imprimas en logs. `SPORTS_OBJECT_ROOT` permite cambiar el almacenamiento local.

## Validación antes de entregar

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
node --test tests/extension/*.test.mjs tests/web/*.test.mjs
uv run python scripts/check_public_repository.py
uv run pip-audit --skip-editable --progress-spinner off
uv build
uv run python scripts/build_site.py --output .local/pages
```

`uv.lock` fija dependencias y hashes; `uv sync --frozen` evita actualizar versiones
durante CI. Las Actions y la imagen PostgreSQL están fijadas por SHA/digest. No se
suben únicamente assets explícitos en el workflow de Pages; CI no publica artifacts.
El chequeo público detecta algunos formatos de credenciales y
archivos prohibidos; es una defensa adicional, no una garantía de detectar todo
secreto posible. `pip-audit` requiere acceso a su índice de vulnerabilidades.

Además del paquete Python existen la extensión local y la web estática con build
y workflow Pages. Un servidor remoto de recepción sigue pendiente. Los fixtures y el object store local funcionan
sin fuentes externas. La integración R2 y Parquet todavía no están conectadas.

## Extensión y navegador de pruebas

`uv sync --frozen` instala Playwright fijado por el lockfile. Los tests buscan
`CHROMIUM_PATH`, después `chromium` del sistema y finalmente el navegador de
Playwright. Si necesitas instalar este último, ejecuta:

```bash
uv run playwright install --with-deps chromium
node --test tests/extension/*.test.mjs
uv run pytest tests/extension
uv run python scripts/package_extension.py .local/sports-capture-extension.zip
```

El empaquetador usa una lista explícita de assets y un ZIP reproducible; rechaza
sobrescribir un destino existente. No requiere npm ni descarga código remoto
para la extensión. CI instala el navegador de Playwright y no sube capturas como
artifacts. La descarga necesita acceso a `cdn.playwright.dev` y los destinos
oficiales de redirección; no se desactiva verificación TLS.

En el cloud actual esa descarga recibió HTTP 403; se validó usando Chromium del
sistema. Además, su política administrativa impide cargar extensiones sin
empaquetar. Las pruebas sirven los assets propios bajo su CSP y simulan APIs
Chrome; ejecutan DOM, formulario, descarga y contrato Python en Chromium real.
Esto no prueba instalación MV3 ni concesión real de activeTab/sidePanel.
El escáner añade pruebas de DOM real, puente de mensajes, permisos simulados,
cancelación/reinicio y contratos JS→Python; no se presentan como una instalación
real del service worker ni como aceptación con las cinco fuentes seleccionadas.
Completa esa aceptación en Chrome/Edge local con la
[guía de instalación](extension/README.md): toolbar, vincular pestaña, seleccionar
un dato público, vista previa/descarga, cambio de pestaña y revocación de acceso.

La [operación del importador](docs/BROWSER_CAPTURE.md) usa solo variables de
entorno para DB/almacenamiento. Las migraciones 0005/0006 se agregan a las cuatro
anteriores sin modificarlas. El recorrido no necesita secretos de producción
cuando se ejecuta sobre el PostgreSQL desechable de desarrollo.

Para capturas automáticas usa `sports-capture import-scan` con el JSON descargado
fuera de Git. Los contratos DOM v2 y conectores v3 conviven con capturas manuales
v1. Los conectores 0.4 se ejecutan en el navegador del usuario: su funcionamiento
no requiere permitir esos hosts en la red cloud. Para desarrollar, los fixtures
de protocolos y los mocks de red son reproducibles; no equivalen a aceptación
real de fuentes. No se requieren
migraciones adicionales; el normalizador v2 mantiene procedencia y fecha de
recepción confiable (normalizador v3 para conectores incluidos). Consulta
[AUTOMATIC_SCANNING.md](docs/AUTOMATIC_SCANNING.md) y ADR 0010.

## Ejecutar la web HTML

```bash
uv run python scripts/serve_site.py --port 8000
```

Construye el sitio y sirve solo ese directorio temporal en loopback, sin listar
directorios ni exponer el checkout. Reinicia el proceso tras modificar assets.
Los tests `uv run pytest tests/web` abren esta misma web en Chromium real;
`node --test tests/web/*.test.mjs` prueba contratos, filtros y fechas Lima.

El build requiere un directorio de salida nuevo: usa otro nombre en una segunda
ejecución. No uses un servidor HTTP sobre la raíz del repositorio. Para exportar
datos públicos desde PostgreSQL, carga de archivos y publicación, consulta
[WEB.md](docs/WEB.md). La web funciona sin PostgreSQL con el calendario vacío o
el ejemplo sintético explícito; no requiere secrets de Actions.

## Cambios futuros

Lee primero [la especificación](docs/PROJECT_SPEC.md) y la
[matriz de estado](docs/IMPLEMENTATION_STATUS.md). Una modificación relevante debe
añadir pruebas de comportamiento, preservar PIT y actualizar los ADRs cuando
cambie una decisión. Nunca uses resultados de holdout para ajustar reglas.

El HTML fuente se conserva fuera del checkout, se ignora por nombre y se excluye
de la lista de archivos empaquetables. No es documentación pública ni un asset.
El contexto permanente es `docs/PROJECT_SPEC.md`.
