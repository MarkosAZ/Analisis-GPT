import { validateSnapshot, filterCycles, latestCycles, localDay, TIMEZONE, SPORTS, STATUS, MAX_BYTES } from './core.mjs';

const $ = id => document.getElementById(id);
const state = { data: null, view: 'partidos', sport: 'ALL', search: '', date: 'ALL', loading: 0 };
const views = { partidos: 'Partidos', seguimiento: 'Seguimiento', historial: 'Historial', extension: 'Extensión' };
const time = value => new Intl.DateTimeFormat('es-PE', { timeZone: TIMEZONE, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value));
const dateTime = value => new Intl.DateTimeFormat('es-PE', { timeZone: TIMEZONE, day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value));
const fullDay = value => new Intl.DateTimeFormat('es-PE', { timeZone: TIMEZONE, weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(value));
function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function message(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}
function badge(cycle) {
  const style = ['POSTPONED', 'CANCELLED'].includes(cycle.status) ? 'closed' : cycle.status === 'ABANDONED' ? 'review' : cycle.tracking_status === 'ACTIVE' ? 'active' : '';
  return node('span', `pill ${style}`, STATUS[cycle.status]);
}
function detail(eventId) {
  const history = state.data.cycles.filter(item => item.event_id === eventId).sort((a, b) => a.cycle_number - b.cycle_number);
  const latest = history.at(-1);
  $('detail-title').textContent = `${latest.home} · ${latest.away}`;
  $('detail-competition').textContent = `${SPORTS[latest.sport]} / ${latest.competition}`;
  $('cycle-history').replaceChildren();
  for (const cycle of history) {
    const item = node('article', 'cycle-item');
    item.append(node('h3', '', `Ciclo ${cycle.cycle_number} · ${STATUS[cycle.status]}`),
      node('p', '', `Programado: ${dateTime(cycle.scheduled_start_at)} · Lima`),
      node('p', '', `Captura vinculada: ${dateTime(cycle.last_observed_at)} · Lima`));
    if (cycle.actual_start_at) item.append(node('p', '', `Inicio real: ${dateTime(cycle.actual_start_at)}`));
    item.append(node('code', '', cycle.event_cycle_id));
    $('cycle-history').append(item);
  }
  $('detail').showModal();
}
function card(cycle) {
  const item = node('article', 'event-card');
  const hour = node('div', 'event-time', time(cycle.scheduled_start_at));
  hour.append(node('small', '', 'LIMA'));
  const info = node('div', 'event-info');
  const title = node('h3');
  title.append(document.createTextNode(cycle.home), node('span', '', 'vs'), document.createTextNode(cycle.away));
  const tracking = { ACTIVE: 'Seguimiento seleccionado', PAUSED: 'Seguimiento pausado', CLOSED: 'Seguimiento cerrado' };
  info.append(node('p', 'competition', `${SPORTS[cycle.sport]} / ${cycle.competition}`), title,
    node('div', 'event-meta', `Ciclo ${cycle.cycle_number}${cycle.tracking_status ? ` · ${tracking[cycle.tracking_status]}` : ' · Sin seguimiento'}`));
  const button = node('button', 'detail-button', 'Ver detalle');
  button.type = 'button';
  button.setAttribute('aria-label', `Ver detalle de ${cycle.home} y ${cycle.away}`);
  button.addEventListener('click', () => detail(cycle.event_id));
  item.append(hour, info, badge(cycle), button);
  return item;
}
function render() {
  const data = state.data;
  const extension = state.view === 'extension';
  $('calendar-view').hidden = extension;
  $('extension-view').hidden = !extension;
  $('breadcrumb').textContent = views[state.view];
  const titles = { partidos: 'Tu próxima lectura\ndel juego.', seguimiento: 'Cada encuentro,\nbajo seguimiento.', historial: 'La historia también\nforma parte del juego.', extension: 'Tus fuentes.\nTu contexto.' };
  $('title').textContent = titles[state.view];
  $('subtitle').textContent = { partidos: 'Consulta el calendario y sigue cada cambio de programación.', seguimiento: 'Ciclos seleccionados o pausados en la última publicación.', historial: 'Consulta cada programación sin perder los ciclos anteriores.', extension: 'Una herramienta local para capturar datos deportivos públicos.' }[state.view];
  for (const anchor of document.querySelectorAll('[data-view]')) {
    if (anchor.dataset.view === state.view) anchor.setAttribute('aria-current', 'page');
    else anchor.removeAttribute('aria-current');
  }
  if (!data) return;
  $('demo-banner').hidden = data.data_kind !== 'SYNTHETIC';
  const latest = latestCycles(data.cycles);
  $('metric-events').textContent = String(latest.length);
  $('metric-tracking').textContent = String(latest.filter(item => item.tracking_status === 'ACTIVE').length);
  $('metric-changes').textContent = String(data.cycles.filter(item => item.cycle_number > 1).length);
  $('metric-updated').textContent = data.generated_at ? dateTime(data.generated_at) : 'Sin datos';
  $('board-title').textContent = { partidos: 'Todos los partidos', seguimiento: 'Tu lista de seguimiento', historial: 'Historial de ciclos', extension: 'Todos los partidos' }[state.view];
  const cycles = filterCycles(data, state);
  $('result-count').textContent = `${cycles.length} ${state.view === 'historial' ? 'ciclos' : 'partidos'}`;
  $('event-list').replaceChildren();
  let previousDay = null;
  for (const cycle of cycles) {
    const day = localDay(cycle.scheduled_start_at);
    if (day !== previousDay) {
      const heading = node('div', 'day-heading');
      heading.append(node('span'), document.createTextNode(fullDay(cycle.scheduled_start_at)));
      $('event-list').append(heading);
      previousDay = day;
    }
    $('event-list').append(card(cycle));
  }
  $('empty').hidden = Boolean(cycles.length);
  $('empty-title').textContent = !data.cycles.length ? 'Tu calendario empieza aquí' : state.view === 'seguimiento' ? 'Sin ciclos en esta selección' : 'No hay partidos con esos filtros';
  $('empty-copy').textContent = !data.cycles.length ? 'Todavía no se han publicado partidos. Explora un ejemplo o carga un calendario público exportado desde el proyecto.' : 'Prueba otro deporte, cambia la fecha o borra la búsqueda. El seguimiento se actualiza desde el importador del proyecto.';
  $('empty-demo').hidden = Boolean(data.cycles.length);
}
function adopt(data, label) {
  state.data = validateSnapshot(data);
  if ($('detail').open) $('detail').close();
  message(`${label} Los estados corresponden a la última publicación.`);
  render();
}
async function fetchSnapshot(path, label) {
  const request = ++state.loading;
  message('Cargando calendario…');
  try {
    const response = await fetch(new URL(path, import.meta.url), { cache: 'no-store', credentials: 'omit', redirect: 'error' });
    if (!response.ok) throw new Error('No se pudo cargar el calendario publicado.');
    const contents = await response.text();
    if (new TextEncoder().encode(contents).length > MAX_BYTES) throw new Error('El calendario supera el tamaño permitido.');
    const data = validateSnapshot(JSON.parse(contents));
    if (path === 'public.json' && data.data_kind !== 'PUBLIC') throw new Error('El calendario publicado no es un snapshot público válido.');
    if (request === state.loading) adopt(data, label);
  } catch {
    if (request === state.loading) message('No se pudo leer el calendario. Recarga la página o carga un archivo público válido.', true);
  }
}
function navigate() {
  state.view = Object.hasOwn(views, location.hash.slice(1)) ? location.hash.slice(1) : 'partidos';
  render();
}
const example = () => { state.sport = 'ALL'; state.search = ''; state.date = 'ALL'; $('search').value = ''; $('date-filter').value = 'ALL'; updateSportButtons(); return fetchSnapshot('demo.json', 'Ejemplo ficticio cargado.'); };
function updateSportButtons() {
  for (const button of document.querySelectorAll('[data-sport]')) button.setAttribute('aria-pressed', String(button.dataset.sport === state.sport));
}
for (const button of document.querySelectorAll('[data-sport]')) button.addEventListener('click', () => { state.sport = button.dataset.sport; updateSportButtons(); render(); });
$('search').addEventListener('input', event => { state.search = event.target.value; render(); });
$('date-filter').addEventListener('change', event => { state.date = event.target.value; render(); });
$('demo').addEventListener('click', example);
$('empty-demo').addEventListener('click', example);
$('live').addEventListener('click', () => fetchSnapshot('public.json', 'Calendario publicado cargado.'));
$('close-detail').addEventListener('click', () => $('detail').close());
$('load-file').addEventListener('click', () => $('snapshot-file').click());
$('snapshot-file').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  const request = ++state.loading;
  try {
    if (file.size > MAX_BYTES) throw new Error('El archivo supera 2 MiB.');
    const data = validateSnapshot(JSON.parse(await file.text()));
    if (request === state.loading) adopt(data, 'Calendario local cargado solo en esta pestaña.');
  } catch {
    if (request === state.loading) message('Archivo rechazado. Usa un calendario público exportado; no se admiten capturas RAW ni datos privados.', true);
  } finally { event.target.value = ''; }
});
window.addEventListener('hashchange', navigate);
navigate();
fetchSnapshot('public.json', 'Calendario publicado cargado.');
