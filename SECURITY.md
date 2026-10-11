# Seguridad del repositorio público

Todos los archivos, logs, inputs de workflows y artifacts públicos se consideran visibles para terceros. Los controles se aplican antes de exportar o ejecutar, no después de producir un archivo que contenga datos privados.

## Secretos y fuentes de contexto

No guardar tokens, contraseñas, DSN completos, credenciales en URLs, secretos derivados o dumps de entorno en código, documentación, logs o fixtures. Los errores de configuración deben mencionar nombres de variables y categorías de fallo, no valores. Una URI persistida de objeto debe ser una referencia sin firma temporal ni credenciales.

El HTML original de diseño es material local de contexto: no es código del proyecto, dato de frontend, dependencia ni artifact. Debe permanecer fuera del checkout o estar ignorado; no se elimina la copia del usuario. La documentación consolidada conserva decisiones, no datos privados o metadata de la conversación.

Los paquetes/artefactos se instalan verificando TLS e integridad. No se deshabilita verificación para sortear una fuente bloqueada. Los providers usarán fuentes autorizadas; no se incluyen mecanismos de evasión de protección.

## Separación SQL

| Rol | Alcance |
| --- | --- |
| `sports_public_worker` | Operación pública necesaria; sin USAGE en `private_betting` ni privilegios de administración de holdout |
| `model_training_worker` | Datos públicos/modelos según permisos explícitos; sin apuestas reales ni desbloqueo ordinario de holdout |
| `private_bets_worker` | Lectura pública mínima necesaria y operación del schema privado |
| Administración de migraciones | DDL y operaciones privilegiadas; credenciales separadas de workers |

Los roles de grupo no son credenciales de login. La provisión de usuarios/contraseñas reales es una tarea de despliegue. No conceder ownership, superuser, BYPASSRLS o membresías administrativas al worker normal; estas capacidades anulan la frontera que se pretende proteger.

La ausencia de UI privada no basta: PostgreSQL debe rechazar una consulta pública al schema privado. Las pruebas de integración deben ejecutar consultas bajo los roles efectivos. Los datos sintéticos de pruebas no representan apuestas reales.

La protección de holdout se aplica mediante permisos y filtros de acceso a las ventanas/resultados relevantes, además del contrato Python. No garantiza por sí sola que cualquier futura feature u objeto RAW resulte inaccesible: la incorporación de fuentes y datasets deberá preservar la misma política.

## Workflows

No usar `pull_request_target`. CI para PRs/forks no recibe secretos de producción. Los workflows con secretos deben limitar triggers y permisos y nunca ejecutar código no confiable proveniente de un PR. CI utiliza datos sintéticos y PostgreSQL temporal.

No pasar `real_bet`, stake, cuota tomada, moneda ni información privada como inputs de un workflow público. El enmascaramiento automático de Actions no protege necesariamente valores derivados; no imprimirlos. Evitar trazas de clientes que incluyan DSN/headers y errores remotos con contenido sensible.

No subir dumps, backups, datasets privados o capturas con credenciales como artifacts. Los artifacts de Pages se generan desde una lista explícita de rutas publicables en `.local/pages`; no empaquetar todo el checkout. Solo el job de despliegue tiene `pages: write` e `id-token: write`, limitado a main del repositorio no fork. El build no recibe credenciales de producción. Los tokens de R2/Neon deben tener el mínimo alcance necesario.

## Repositorio privado futuro

El registro de apuestas reales, sus secretos y `real_bets.json` se alojan en un segundo repositorio privado. El worker público nunca hace de intermediario para datos reales. Las revisiones privadas permanecen en `private_betting.review_queue`; ni su existencia se publica en la cola pública.

La futura interfaz emplea tokens diferentes:

- `SPORTS_ACTIONS_TOKEN`: `Actions: write` sobre el repositorio público para análisis.
- `PRIVATE_BETS_TOKEN`: `Actions: write` y `Contents: read` sobre el repositorio privado para registro y lectura.

No se implementa ese repositorio ni captura de tokens en este incremento. Un PAT fine-grained aplica sus permisos al conjunto de repositorios elegidos; no ofrece permisos distintos por repositorio dentro del mismo token.

## Extensión de captura pública

El manifest solicita solo `activeTab`, `scripting` y `sidePanel`, sin hosts
permanentes. No recoge cookies, credenciales o tráfico ni sube datos. La CSP
prohíbe conexiones y marcos; scripts y estilos son locales. El selector se activa
por el usuario, usa una capa que evita pulsar el botón original, caduca y rechaza
formularios/boletas conocidos. No es una garantía sobre cualquier DOM hostil:
la revisión de campos públicos sigue siendo obligatoria.

El importador limita el tamaño a 16 KiB, exige campos exactos y decimales válidos,
rechaza campos privados/fechas inválidas y no imprime excepciones del driver.
Solo persiste origen HTTPS, nunca ruta/query ni HTML completo. Las capturas
`sports-capture-*.json` están ignoradas y el scanner las rechaza incluso si se
añadiesen forzosamente. El ZIP usa una lista fija de ocho assets de la extensión.

Las credenciales PostgreSQL viven únicamente en el entorno del importador. Los
roles públicos conservan la denegación sobre `private_betting`. Este incremento
no incluye subida remota, apuestas reales ni nuevos secretos de Actions.

## Frontend y exportaciones

GitHub Pages no se conecta a PostgreSQL. Consume JSON públicos versionados y mínimos. La CSP de `index.html` limita scripts, estilos y conexiones al propio sitio; no hay dependencias remotas, iframes ni captura de tokens. Pages no permite controlar todos los encabezados de respuesta. Una futura sección privada necesitará una revisión independiente de permisos.

El contrato `public_calendar_v1` rechaza claves extra, cadenas de ciclos rotas y
observaciones posteriores a la generación. Tiene límites de 2 MiB y 5000 ciclos;
los textos se muestran mediante `textContent`. Los archivos elegidos por el
usuario se validan en memoria, sin subida ni persistencia. No acepta capturas RAW.
El directorio del servidor local se construye de forma aislada y no lista rutas.

Antes de publicar, comprobar los campos permitidos, las rutas incluidas y la ausencia del HTML de contexto, configuración local, objetos privados y dumps. Los backups pertenecen a object storage privado con una política propia de acceso/retención.

## Operación

Sanitizar resúmenes de errores, revisar permisos al desplegar y rotar credenciales fuera del repositorio. La supervisión de los cron debe detectar su posible desactivación tras inactividad. Recuperar trabajos sin inventar observaciones retrospectivas y sin divulgar datos durante el diagnóstico.
