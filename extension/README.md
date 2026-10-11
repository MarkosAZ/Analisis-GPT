# Captura y escaneo deportivo — extensión local 0.3

Extensión Manifest V3 para Chrome 116+ y Edge compatible con `sidePanel`.
Inicia el escaneo desde la web de Analisis-GPT. El panel lateral conserva la captura manual como alternativa.
No incrusta webs en iframes: respeta sus restricciones de navegación y framing.

## Instalar

1. Descarga y descomprime `sports-capture-extension.zip`, o usa la carpeta
   `extension/` del repositorio.
2. Abre `chrome://extensions` (Edge: `edge://extensions`).
3. Activa **Modo de desarrollador**, pulsa **Cargar descomprimida** y selecciona
   la carpeta que contiene `manifest.json`.
4. Fija la extensión a la barra para poder conceder acceso a la pestaña deseada.

Es una instalación local, no una publicación en Chrome Web Store. No necesita
claves, cuenta propia ni servidor. Firefox todavía no está soportado.

## Escaneo automático

1. Actualiza la extensión y recarga la web de Analisis-GPT.
2. En la sección Extensión pulsa **Configurar fuentes**, carga perfiles verificados
   y concede permiso de lectura a sus sitios una vez.
3. Pulsa **Iniciar escaneo**: abre una página cada vez, espera datos, lee campos
   públicos y devuelve las capturas. Puedes cancelar y descargar el lote terminado.
4. Importa con `uv run sports-capture import-scan /ruta/sports-scan-UUID.json`.

**Abrir las cinco fuentes** abre SofaScore, Betano Perú, Apuesta Total, Te Apuesto
 y Flashscore Perú. Sus lectores reales siguen pendientes porque la red cloud
bloqueó la inspección. No confundas ese botón con extracción de cuotas. El motor
funciona con perfiles válidos y está probado con fixtures; no hay perfiles reales
inventados ni extracción universal de cualquier página.

Consulta la [guía completa](https://github.com/MarkosAZ/Analisis-GPT/blob/main/docs/AUTOMATIC_SCANNING.md).

## Capturar manualmente

1. Abre una página pública de SofaScore, Betano u otra fuente que tengas permiso
   de consultar. Puedes escribir su URL en el panel y pulsar **Abrir**.
2. Pulsa el icono de la extensión en esa pestaña y **Usar pestaña actual**.
   Vincular una pestaña inicia un formulario vacío.
3. Elige **Partido / calendario** o **Mercado de cuotas**.
4. Completa los campos. El botón **Elegir** permite elegir un texto visible con un
   clic. Esc cancela y la selección caduca a los 30 segundos. El selector evita
   hacer clic sobre el botón de cuota original. No funciona dentro de iframes.
5. Usa IDs públicos estables; no inventes uno nuevo al recapturar el mismo
   partido. Las fechas son ISO con zona, por ejemplo `2030-06-15T20:00:00-05:00`.
   Las cuotas son decimales con punto. No se interpretan fechas regionales ni
   se convierten cuotas fraccionales automáticamente.
6. Un mercado corresponde a **una casa, un evento, un periodo y una línea**;
   completa todos los resultados. Three-way exige tres. Las enteras y asiáticas
   se conservan sin hacerlas elegibles para `line_selector_v1`.
7. Pulsa **Preparar vista previa**, revisa el JSON, confirma y descárgalo. Una
   nueva vista previa crea otra observación; descargarla otra vez conserva el
   UUID para que la importación sea idempotente.

El formulario se guarda solo en memoria: cerrar el panel o recargarlo puede
perder datos sin exportar. Cambiar de página obliga a vincularla y recapturar.
Este modo manual no recorre páginas. El motor automático espera datos DOM con
límites por fuente; no intercepta tráfico, evade bloqueos ni usa APIs internas.

## Límites de privacidad y procedencia

Permisos: `activeTab`, `scripting`, `sidePanel` y `storage`. El modo automático
solicita acceso opcional solo a los hosts de los perfiles elegidos. El puente se
limita a la web del proyecto y desarrollo local; no hay acceso a cookies, historial
o tráfico, ni almacenamiento de credenciales. No hay
subida automática. Se exporta únicamente el origen HTTPS, sin ruta, query ni
fragmento. Nunca uses formularios de cuenta, saldo, boletas o apuestas realizadas.
El selector rechaza patrones sensibles conocidos y el importador exige campos
exactos. Estos filtros no pueden certificar que cualquier página o texto escrito
manualmente sea público: la revisión antes de exportar sigue siendo necesaria.

Las capturas automáticas se etiquetan `AUTOMATIC_DOM` / `DOM_UNVERIFIED`, conservan
lector y perfil/hash, y nunca se presentan como revisión humana. Los perfiles
son locales; capturas y progreso viven en sesión hasta cerrar el navegador.
Cada captura manual se etiqueta `MANUAL_REVIEW` y, al importarse, `MANUAL_UNVERIFIED`.
No certifica autenticidad del proveedor ni simultaneidad de todas las cuotas.
El reloj del navegador no demuestra disponibilidad histórica. El servidor fija
la recepción; la normalización y resolución de mappings registran su propio
instante disponible. Una importación tardía no rellena huecos del pasado.

## Importar en el proyecto

Desde el checkout con Python/uv, PostgreSQL migrado y `DATABASE_URL` configurada
en el entorno, sin incluirla en argumentos ni en la extensión:

```bash
uv run sports-capture import /ruta/privada/sports-capture-UUID.json
uv run sports-capture pending-mappings
```

El calendario necesita confirmación explícita de identidades antes de crear
eventos. El procedimiento completo está en `docs/BROWSER_CAPTURE.md` del repo.
Las cuotas se archivan para la fase 3; no generan predicciones ni apuestas.
Conserva los JSON y perfiles fuera de Git. El ZIP contiene únicamente los assets
explícitos de esta extensión, nunca capturas ni la conversación HTML original.
