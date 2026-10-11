const $ = id => document.getElementById(id);
const labels = { RUNNING: 'Escaneando', PENDING: 'En cola', COMPLETED: 'Completado', COMPLETED_WITH_ERRORS: 'Completado con incidencias', FAILED: 'No se pudo leer', CANCELLED: 'Cancelado', INTERRUPTED: 'Interrumpido' };
const errors = { BUSY: 'Ya hay un escaneo en marcha.', COOLDOWN: 'Espera un minuto entre inicios de escaneo.', NEEDS_CONFIG: 'Configura las fuentes desde la extensión.', NEEDS_PERMISSIONS: 'Falta permiso para una fuente. Abre Configurar fuentes.', NOT_FINISHED: 'Espera a que termine el escaneo o cancélalo.', DISCONNECTED: 'No se detectó la extensión. Instala o actualiza el ZIP y recarga esta página.' };
const sourceErrors = { NEEDS_PERMISSIONS: 'permiso pendiente', SOURCE_CHANGED: 'la página cambió de dirección', ACCESS_RESTRICTED: 'acceso restringido', ROW_LIMIT: 'demasiadas filas', PRIVATE_FIELD: 'campo sensible o no visible', AMBIGUOUS_FIELD: 'el campo no es único', INVALID_FIELD: 'dato no válido', INVALID_SELECTOR: 'el lector necesita revisión', READ_FAILED: 'no se pudo leer el dato', TIMEOUT: 'no llegaron datos a tiempo', CAPTURE_LIMIT: 'límite de capturas alcanzado' };
const requests = new Map();
let connected = false;
let busy = false;
let current = null;
let timer;
const notice = value => { $('scanner-notice').textContent = value; };
window.addEventListener('message', event => {
  if (event.source !== window || event.origin !== location.origin || event.data?.channel !== 'sports_scan_response_v1') return;
  const waiting = requests.get(event.data.request_id);
  if (!waiting) return;
  requests.delete(event.data.request_id); clearTimeout(waiting.timeout);
  if (event.data.result?.ok) waiting.resolve(event.data.result.data);
  else waiting.reject(new Error(event.data.result?.error || 'DISCONNECTED'));
});
function request(command) {
  const request_id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { requests.delete(request_id); reject(new Error('DISCONNECTED')); }, 4000);
    requests.set(request_id, { resolve, reject, timeout });
    window.postMessage({ channel: 'sports_scan_request_v1', request_id, command }, location.origin);
  });
}
function render(data) {
  connected = true; current = data;
  const run = data.run;
  const running = run?.status === 'RUNNING';
  $('scanner-start').disabled = busy || running || !data.configured || !data.permitted;
  $('scanner-cancel').disabled = busy || !running;
  $('scanner-download').disabled = busy || !run || running || !run.count;
  $('scanner-configure').disabled = busy || running;
  $('scanner-open-sources').disabled = busy || running;
  $('scanner-count').textContent = `${data.configured} fuentes configuradas${run ? ` · ${run.count} capturas` : ''}`;
  $('scanner-state').textContent = run ? labels[run.status] || 'Estado desconocido' : 'Extensión conectada';
  $('scanner-sources').replaceChildren();
  for (const source of run?.sources || []) {
    const row = document.createElement('li');
    row.textContent = `${source.label} · ${labels[source.status] || 'Sin estado'} · ${source.count} capturas${source.error ? ` (${sourceErrors[source.error] || 'incidencia de lectura'})` : ''}`;
    $('scanner-sources').append(row);
  }
  if (!data.configured) notice('Configura las fuentes una vez. Después la extensión abrirá y leerá las páginas por ti.');
  else if (!data.permitted) notice(errors.NEEDS_PERMISSIONS);
  else if (running) notice('La extensión recorre las fuentes. Mantén abierta esta pestaña; puedes cancelar en cualquier momento.');
  else if (run) notice('Las capturas quedan en tu navegador. Descárgalas para importarlas; todavía no son partidos publicados ni predicciones.');
  else notice('Todo listo para iniciar el recorrido de tus fuentes.');
}
async function refresh() {
  if (busy) return;
  try { const data = await request('STATUS'); if (!busy) render(data); }
  catch { connected = false; $('scanner-state').textContent = 'Extensión no conectada'; for (const id of ['scanner-start', 'scanner-configure', 'scanner-open-sources', 'scanner-cancel', 'scanner-download']) $(id).disabled = true; notice(errors.DISCONNECTED); }
  finally { clearTimeout(timer); if (connected) timer = setTimeout(refresh, 2000); }
}
async function act(command) {
  if (busy) return;
  busy = true; clearTimeout(timer);
  let failed = false;
  for (const id of ['scanner-start', 'scanner-cancel', 'scanner-download', 'scanner-configure', 'scanner-open-sources']) $(id).disabled = true;
  try {
    const data = await request(command);
    if (command === 'RESULTS') {
      if (data?.schema_version !== 'browser_scan_v1' || !Array.isArray(data.captures) || data.captures.length > 200) throw new Error('INVALID_RESULT');
      const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' });
      if (blob.size > 4 * 1024 * 1024) throw new Error('INVALID_RESULT');
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `sports-scan-${data.scan_id}.json`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notice('Escaneo descargado. Se conserva la fecha original de cada lectura.');
    } else if (command === 'OPEN_SOURCES') notice('Se abrieron las cinco fuentes. La lectura de sus datos necesita perfiles verificados.');
    else if (command === 'CONFIGURE') notice('Configuración abierta en una pestaña de la extensión.');
    else current = data;
  } catch (error) { failed = true; notice(errors[error.message] || 'No se pudo completar la operación. Comprueba la extensión.'); }
  finally {
    busy = false;
    if (current) {
      const message = $('scanner-notice').textContent;
      render(current);
      if (failed || (command !== 'START' && command !== 'CANCEL')) notice(message);
    }
    timer = setTimeout(refresh, 2000);
  }
}
$('scanner-connect').addEventListener('click', refresh);
for (const [id, command] of [['scanner-start', 'START'], ['scanner-cancel', 'CANCEL'], ['scanner-download', 'RESULTS'], ['scanner-configure', 'CONFIGURE'], ['scanner-open-sources', 'OPEN_SOURCES']]) $(id).addEventListener('click', () => act(command));
refresh();
