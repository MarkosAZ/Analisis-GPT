# Escaneo automático desde la web

La extensión 0.4 implementa el recorrido automático solicitado por el usuario.
Desde la sección **Extensión** de Analisis-GPT se inicia una cola de páginas:
abrir, esperar sus datos, leer campos públicos y devolver capturas. No requiere
seleccionar cada dato en cada ejecución. El modo manual 0.2 sigue compatible.

## Conectores incluidos

La [referencia aportada por el usuario](https://github.com/LuisP11127/Analisis-BDP/tree/7b0dcd97b4db471057508ba47df04b0bb0d4ccaa/extension)
permitió incorporar lectores específicos. Elige fuentes con casillas y concede
acceso una vez; no necesitas escribir JSON. Las consultas salen del navegador.

| Fuente | Entrada pública | Lector real |
| --- | --- | --- |
| SofaScore | https://www.sofascore.com/ | Calendario de fútbol de hoy, filtrado por Lima |
| Betano Perú | https://www.betano.pe/ | Mercados compatibles del estado público de la página de fútbol |
| Apuesta Total | https://www.apuestatotal.com/apuestas-deportivas/ | ML0/OU0 de hasta diez partidos de fútbol de hoy |
| Te Apuesto | https://www.teapuesto.pe/sport | No implementado |
| Flashscore Perú | https://www.flashscore.pe/ | Calendario de fútbol de hoy, feed Perú/Lima |

Los cuatro conectores están implementados y probados con fixtures de los formatos
inspeccionados. **La aceptación con sitios reales sigue pendiente.** El cloud
había rechazado sus conexiones con 403 de túnel; eso no demuestra que el proveedor
rechace el navegador del usuario. Ejecutar la extensión no requiere cambiar la
red del cloud. Te Apuesto tampoco aparece en la referencia y permanece pendiente.

**Abrir las cinco fuentes** abre esas URLs automáticamente. No se presenta como
una extracción. **Iniciar escaneo** ejecuta los conectores activados; permanece
deshabilitado si no existen o faltan permisos. Ningún fixture se activa como fuente.

## Operación

1. Actualiza la extensión descomprimida desde el nuevo ZIP o la carpeta `extension/`.
   Recarga también la página web para que aparezca el puente de conexión.
2. Abre **Extensión → Configurar fuentes**, selecciona las casillas y pulsa
   **Activar fuentes seleccionadas**. Chrome/Edge solicita acceso a esos sitios
   y a sus hosts de datos, mostrados junto a cada fuente. Los perfiles DOM propios
   quedan como opción avanzada.
3. Vuelve a la web y pulsa **Iniciar escaneo**. Las pestañas de captura se abren
   secuencialmente en segundo plano. Mantén abierta la pestaña que inició el run.
4. Consulta estado por fuente, número de capturas y vista previa. **Descargar
   diagnóstico** conserva errores, lector/versión y contadores incluso sin capturas.
   **Cancelar** detiene el trabajo
   pendiente y descarta respuestas tardías. Un error de fuente queda visible;
   no se convierte en cuotas inventadas ni en una captura exitosa vacía.
5. Descarga el lote terminado, cancelado o interrumpido si contiene capturas.
   El resultado permanece en memoria de sesión del navegador y no se sube.
6. Importa el archivo fuera de Git, con PostgreSQL y object storage configurados:

```bash
uv run sports-capture import-scan /ruta/privada/sports-scan-UUID.json
```

Se valida el lote entero antes de importar. Cada miembro tiene bytes canónicos,
UUID propio, RAW inmutable y recibo SQL. Si una escritura falla a mitad de lote,
reintentar el mismo archivo reutiliza los miembros ya importados. No se promete
una transacción atómica que abarque SQL y object storage.

Las identidades todavía requieren confirmación antes de actualizar el calendario.
Las cuotas se guardan RAW_ONLY: no hay predicciones, benchmarks ni apuestas.
Para exportar el calendario publicado sigue [BROWSER_CAPTURE.md](BROWSER_CAPTURE.md).

## Alcance de los conectores

- SofaScore consulta dos rutas `scheduled-events` en `www.sofascore.com` para
  cubrir el día completo de Lima. Exige IDs estables; no convierte un horario
  programado en inicio real de un partido finalizado.
- Flashscore usa el feed Perú de fútbol en `global.flashscore.ninja`, zona -5 y
  la cabecera de protocolo pública de la referencia. No descubre hosts ni prueba
  feeds alternativos tras una denegación. Faltas de IDs no se rellenan con nombres.
- Betano abre `/sport/futbol/` y proyecta eventos/mercados de su estado público
  incrustado. No instala hooks de fetch/XHR, no transfiere el estado completo ni
  pulsa cuotas. Reconoce 1X2, ambos anotan y totales de goles de partido completo,
  con nombres compatibles y sin periodos explícitos contradictorios. No recorre
  cada partido ni garantiza leer mercados cargados exclusivamente por tráfico
  posterior que no estén en ese estado.
- Apuesta Total consulta snapshot y una petición acotada de ML0/OU0 en
  `prod20392.kmianko.com`. Puede usar la sesión que el navegador envía normalmente
  al sportsbook abierto; no lee esa cookie ni fuerza login/logout o sesión nueva.
  Si requiere autorización o deniega la consulta, lo indica sin reintentar.

Las solicitudes usan rutas fijas, timeout de 12 segundos, máximo 2 MiB y rechazo
de redirecciones. Hay hasta dos peticiones API por fuente/recorrido; Betano solo
lee su página. Un 401/403/429 termina esa fuente. Cuotas contradictorias del mismo
mercado producen AMBIGUOUS_SOURCE; no se elige silenciosamente una. Se cuentan
registros incompatibles y exceso sobre 50 capturas, sin afirmar cobertura total.

El diagnóstico distingue acceso denegado, sesión requerida, rate limit, red,
formato cambiado, ausencia de datos y timeout. No incluye HTML, cuerpos HTTP,
cookies, encabezados de cuenta ni credenciales. Se descarga localmente, incluso
si no hubo capturas; no es un lote para el importador. La vista previa muestra
hasta veinte capturas sin agregarlas al calendario público.

## Contrato de perfiles para desarrollar lectores

La configuración `browser_scan_config_v1` contiene `sources` con hasta diez
perfiles. Los conectores incluidos tienen ID/versión/URL/lector/tipo/deporte fijos;
no se pueden cambiar por código o endpoints arbitrarios. Un perfil DOM avanzado
fija `id`, `version`, `label`, `url`, `reader`, `kind`,
`row_selector` y `fields`. El lector `dom_fields_v1` lee filas visibles: una fila
es exactamente un evento o un mercado completo. No agrupa por similitud ni rellena
datos ausentes. El selector de cada campo debe encontrar un único elemento dentro
de la fila; `:scope` permite leer un atributo de esa misma fila.

Ejemplo **sintético**, útil para un HTML propio con una fila `.market` y los campos
indicados. No es un lector de Betano ni de otra fuente real:

```json
{
  "schema_version": "browser_scan_config_v1",
  "sources": [{
    "id": "fixture",
    "version": "1",
    "label": "Ejemplo local de contrato",
    "url": "https://fixture.example/markets",
    "reader": "dom_fields_v1",
    "kind": "ODDS",
    "row_selector": ".market",
    "fields": {
      "event_id": {"selector": ":scope", "attribute": "data-event-id"},
      "sport": {"value": "FOOTBALL"},
      "bookmaker": {"value": "Fixture Book"},
      "market": {"value": "TOTAL_GOALS"},
      "period": {"value": "FULL_TIME"},
      "line_type": {"value": "HALF_LINE"},
      "line": {"selector": ".line", "attribute": null},
      "outcome_1": {"value": "OVER"},
      "odds_1": {"selector": ".price-one", "attribute": null},
      "outcome_2": {"value": "UNDER"},
      "odds_2": {"selector": ".price-two", "attribute": null}
    }
  }]
}
```

Los literales se permiten solo para metadata del mercado/deporte; IDs de evento,
equipos, fechas, líneas y precios deben leerse del DOM. No se permiten JavaScript,
lectura de cookies, HTML completo, atributos arbitrarios o acceso a `value` de
formularios. Los atributos admitidos son `datetime` y `data-*`; los textos se
validan igual que en el contrato público. IDs deben ser estables de la fuente.

`CALENDAR` exige evento/deporte, IDs y nombres de competición/local/visitante,
fecha programada y estado; inicio real es opcional salvo FINISHED. `ODDS` exige
evento/deporte/casa/mercado/periodo/tipo y resultados completos; tres vías requiere
tres, y las líneas numéricas no se convierten a otro tipo. Fechas ISO con zona y
cuotas decimales con punto. No hay conversiones regionales implícitas.

Al cambiar selectores, incrementa `version`. Cada captura conserva SHA-256 del
perfil completo serializado canónicamente, además de ID/versión y lector. El hash
permite distinguir dos configuraciones incluso si su autor reutiliza una versión.
Conserva los perfiles de producción en almacenamiento local privado; no contienen
secretos, pero no forman parte del artifact público del sitio.

## Límites, recuperación y permisos

- Una cola a la vez; un minuto entre inicios, dos segundos entre páginas,
  treinta segundos máximos de espera por fuente, 50 filas por fuente y 200 por run.
- No descubrir enlaces arbitrarios ni recorrer todos los partidos desde una portada.
  Esa navegación necesita un lector específico verificado y límites propios.
- No clicar cuotas, consentimientos, login, formularios, botones de apuesta o CAPTCHA.
  Redirecciones, contenido privado conocido, campos ambiguos y accesos restringidos
  producen incidencia. El código no garantiza reconocer cualquier DOM sensible.
- Solo se cierran pestañas creadas por el run que siguen en su URL configurada;
  se conserva una pestaña si el usuario la navega a otro destino.
  Los conectores incluidos admiten unas pocas redirecciones iniciales de idioma
  dentro de su mismo host; después fijan la dirección resuelta. Una navegación
  pendiente a otro destino también impide el cierre. Los perfiles DOM siguen
  exigiendo su URL exacta.
- El cierre de la pestaña iniciadora cancela el run. Un reinicio del service worker
  marca RUNNING como INTERRUPTED y conserva capturas completadas; no vuelve a abrir
  fuentes automáticamente. Cerrar el navegador borra `storage.session`.
- Los perfiles se guardan en `storage.local`, sin sincronización remota. Los dos
  almacenes se restringen a contextos confiables. Quitar fuentes retira sus permisos.
- Solo la página interna de configuración modifica perfiles. La web del proyecto
  envía comandos acotados, nunca URLs/perfiles/scripts. El puente verifica origen,
  ruta y frame; desarrollo local admite únicamente el puerto 8000.

## Procedencia y temporalidad

Los conectores incluidos usan `browser_capture_v3`, AUTOMATIC_SOURCE, normalizador
v3 y calidad SOURCE_UNVERIFIED. El backend vincula lector, perfil, versión,
deporte, tipo y origen. Las versiones anteriores no se reinterpretan.
`browser_capture_v2` añade `capture_method=AUTOMATIC_DOM`, `scan_id`,
`reader_version`, `profile_id`, `profile_version` y `profile_hash`. El backend
mantiene calidad `DOM_UNVERIFIED`, normalizador v2 y disponibilidad fijada por
recepción SQL. Capturar antes no permite importar información al pasado.
La fecha declarada del navegador no es una certificación de la fuente.

`browser_scan_v1` contiene `scan_id`, `started_at`, `finished_at`, estado terminal
y capturas. No incluye HTML, URLs completas, credenciales ni apuestas. Los
archivos `sports-scan-*.json` y `scan-profiles*.json` están ignorados y bloqueados
por el scanner del repositorio. Capturas manuales v1 y sus manifests se conservan.

## Verificación pendiente con sitios reales

Instala el ZIP en Chrome/Edge local y contrasta las capturas con las páginas
autorizadas. Revisa el diagnóstico si una fuente no responde o cambia su formato.
No hace falta publicar el entorno cloud para ejecutar el escáner. Prueba
instalación MV3, concesión/revocación de hosts,
puente Pages, pestañas, suspensión del worker y descarga/importación.

El navegador administrado del cloud prohíbe instalar extensiones descomprimidas.
Los tests actuales ejecutan UI/DOM en Chromium con APIs Chrome simuladas y pruebas
del controlador; no eluden esa política ni equivalen a esa aceptación real.
