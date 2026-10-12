const $ = id => document.getElementById(id);
const labels = { RUNNING: 'Escaneando', PENDING: 'En cola', COMPLETED: 'Completado', COMPLETED_WITH_ERRORS: 'Completado con incidencias', FAILED: 'No se pudo leer', CANCELLED: 'Cancelado', INTERRUPTED: 'Interrumpido' };
const errors = { BUSY: 'Ya hay un escaneo en marcha.', COOLDOWN: 'Espera un minuto entre inicios de escaneo.', NEEDS_CONFIG: 'Configura las fuentes desde la extensión.', NEEDS_PERMISSIONS: 'Falta permiso para una fuente. Abre Configurar fuentes.', NOT_FINISHED: 'Espera a que termine el escaneo o cancélalo.', DISCONNECTED: 'No se detectó la extensión. Instala o actualiza el ZIP y recarga esta página.' };
const sourceErrors = { NEEDS_PERMISSIONS: 'permiso pendiente', SOURCE_CHANGED: 'la página cambió de dirección', ACCESS_RESTRICTED: 'acceso restringido', ROW_LIMIT: 'demasiadas filas', PRIVATE_FIELD: 'campo sensible o no visible', AMBIGUOUS_FIELD: 'el campo no es único', INVALID_FIELD: 'dato no válido', INVALID_SELECTOR: 'el lector necesita revisión', READ_FAILED: 'no se pudo leer el dato', TIMEOUT: 'no llegaron datos a tiempo', CAPTURE_LIMIT: 'límite de capturas alcanzado', HTTP_401: 'la fuente requiere autorización', HTTP_403: 'la fuente denegó la consulta', HTTP_429: 'límite de solicitudes de la fuente', SOURCE_HTTP_ERROR: 'la fuente devolvió un error', NETWORK_ERROR: 'no se pudo conectar desde el navegador', RESPONSE_LIMIT: 'respuesta demasiado grande', SCHEMA_CHANGED: 'formato no compatible: el lector necesita revisión', AMBIGUOUS_SOURCE: 'datos contradictorios: no se mezclaron', NO_PUBLIC_DATA: 'no hay datos públicos compatibles' };
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
  $('scanner-report').disabled = busy || !run || running;
  $('scanner-configure').disabled = busy || running;
  $('scanner-open-sources').disabled = busy || running;
  $('scanner-count').textContent = `${data.configured} fuentes configuradas${run ? ` · ${run.count} capturas` : ''}`;
  $('scanner-state').textContent = run ? labels[run.status] || 'Estado desconocido' : 'Extensión conectada';
  $('scanner-sources').replaceChildren();
  for (const source of run?.sources || []) {
    const row = document.createElement('li');
    row.textContent = `${source.label} · ${labels[source.status] || 'Sin estado'} · ${source.count} capturas${source.error ? ` (${sourceErrors[source.error] || 'incidencia de lectura'})` : ''}${source.skipped ? ` · ${source.skipped} registros no compatibles` : ''}${source.truncated ? ` · ${source.truncated} fuera del límite` : ''}`;
    $('scanner-sources').append(row);
  }
  $('scanner-preview-list').replaceChildren();
  const preview = Array.isArray(run?.preview) ? run.preview.slice(0, 20) : [];
  $('scanner-preview').hidden = !preview.length;
  for (const capture of preview) {
    const row = capture.record; if (!row) continue;
    const card = document.createElement('article'); card.className = 'capture-preview';
    const title = document.createElement('strong'); const detail = document.createElement('p'); const stamp = document.createElement('small');
    if (capture.kind === 'CALENDAR') {
      title.textContent = `${row.home_name} — ${row.away_name}`;
      detail.textContent = `${row.competition_name} · ${new Date(row.scheduled_start_at).toLocaleString('es-PE', { timeZone: 'America/Lima' })} · ${row.status}`;
    } else {
      title.textContent = `${row.bookmaker} · evento ${row.event_id}`;
      detail.textContent = `${row.market}${row.line !== null ? ` (${row.line})` : ''} · ${(row.outcomes || []).map(outcome => `${outcome.code}: ${outcome.decimal_odds}`).join(' / ')}`;
    }
    stamp.textContent = `${capture.source_origin} · observado ${new Date(capture.captured_at).toLocaleString('es-PE', { timeZone: 'America/Lima' })}`;
    card.append(title, detail, stamp); $('scanner-preview-list').append(card);
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
  catch { connected = false; $('scanner-state').textContent = 'Extensión no conectada'; for (const id of ['scanner-start', 'scanner-configure', 'scanner-open-sources', 'scanner-cancel', 'scanner-download', 'scanner-report']) $(id).disabled = true; notice(errors.DISCONNECTED); }
  finally { clearTimeout(timer); if (connected) timer = setTimeout(refresh, 2000); }
}
async function act(command) {
  if (busy) return;
  busy = true; clearTimeout(timer);
  let failed = false;
  for (const id of ['scanner-start', 'scanner-cancel', 'scanner-download', 'scanner-configure', 'scanner-open-sources', 'scanner-report']) $(id).disabled = true;
  try {
    const data = await request(command);
    if (command === 'RESULTS' || command === 'REPORT') {
      if (command === 'RESULTS' && (data?.schema_version !== 'browser_scan_v1' || !Array.isArray(data.captures) || data.captures.length > 200)) throw new Error('INVALID_RESULT');
      if (command === 'REPORT' && (data?.schema_version !== 'browser_scan_report_v1' || !Array.isArray(data.sources) || data.sources.length > 10)) throw new Error('INVALID_RESULT');
      const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' });
      if (blob.size > 4 * 1024 * 1024) throw new Error('INVALID_RESULT');
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `sports-scan-${command === 'REPORT' ? 'report-' : ''}${data.scan_id}.json`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notice(command === 'REPORT' ? 'Diagnóstico descargado: estados, contadores y códigos de error, sin cuentas ni credenciales.' : 'Escaneo descargado. Se conserva la fecha original de cada lectura.');
    } else if (command === 'OPEN_SOURCES') notice('Se abrieron las cinco fuentes. Usa Iniciar escaneo para ejecutar los conectores que activaste.');
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
for (const [id, command] of [['scanner-start', 'START'], ['scanner-cancel', 'CANCEL'], ['scanner-download', 'RESULTS'], ['scanner-report', 'REPORT'], ['scanner-configure', 'CONFIGURE'], ['scanner-open-sources', 'OPEN_SOURCES']]) $(id).addEventListener('click', () => act(command));
refresh();
