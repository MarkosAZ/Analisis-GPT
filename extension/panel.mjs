import { buildCapture, publicLocation, SPORTS, STATUSES, LINE_TYPES } from './core.mjs';
import { pickPublicText } from './picker.mjs';

const $ = id => document.getElementById(id);
let source = null;
let preview = null;
let picking = false;
let generation = 0;
const status = message => { $('notice').textContent = message; };
const common = [['event_id', 'ID público del evento'], ['sport', 'Deporte', SPORTS]];
const calendar = [
  ['competition_id', 'ID de competición'], ['competition_name', 'Competición'],
  ['home_id', 'ID del equipo local'], ['home_name', 'Equipo local'],
  ['away_id', 'ID del visitante'], ['away_name', 'Equipo visitante'],
  ['scheduled_start_at', 'Inicio programado (ISO con zona)'], ['status', 'Estado', STATUSES],
  ['actual_start_at', 'Inicio real (si se conoce)'],
];
const odds = [
  ['bookmaker', 'Casa de apuestas'], ['market', 'Mercado (ej. TOTAL_GOALS)'],
  ['period', 'Periodo (ej. FULL_TIME)'], ['line_type', 'Tipo de línea', LINE_TYPES], ['line', 'Línea numérica'],
  ['outcome_1', 'Resultado 1 (ej. OVER)'], ['odds_1', 'Cuota decimal 1'],
  ['outcome_2', 'Resultado 2 (ej. UNDER)'], ['odds_2', 'Cuota decimal 2'],
  ['outcome_3', 'Resultado 3 (solo tres vías)'], ['odds_3', 'Cuota decimal 3'],
];
const labels = {
  FOOTBALL: 'Fútbol', BASKETBALL: 'Baloncesto', BASEBALL: 'Béisbol',
  SCHEDULED: 'Programado', IN_PROGRESS: 'En juego', FINISHED: 'Finalizado',
  POSTPONED: 'Aplazado', CANCELLED: 'Cancelado', ABANDONED: 'Abandonado',
  MONEYLINE: 'Ganador · dos lados', THREE_WAY: 'Resultado · tres vías',
  HALF_LINE: 'Media línea · ej. 2.5', INTEGER_PUSH: 'Entera con push · ej. 3',
  ASIAN_QUARTER: 'Cuarto asiático · ej. 2.25',
};
function invalidate() {
  generation += 1;
  preview = null;
  $('review').hidden = true;
  $('json').textContent = '';
  $('confirmed').checked = false;
  $('download').disabled = true;
}
function render() {
  invalidate();
  $('capture-form').replaceChildren();
  for (const [name, label, choices] of [...common, ...($('kind').value === 'CALENDAR' ? calendar : odds)]) {
    const title = document.createElement('label');
    title.htmlFor = name; title.textContent = label;
    const row = document.createElement('div'); row.className = 'row';
    const input = document.createElement(choices ? 'select' : 'input');
    input.id = name; input.name = name;
    if (choices) for (const value of choices) { const option = document.createElement('option'); option.value = value; option.textContent = labels[value] || value; input.append(option); }
    else { input.type = 'text'; input.maxLength = 100; input.spellcheck = false; }
    input.addEventListener('input', invalidate);
    row.append(input);
    if (!choices) {
      const pick = document.createElement('button');
      pick.type = 'button'; pick.className = 'pick'; pick.textContent = 'Elegir';
      pick.setAttribute('aria-label', `Elegir ${label} en la página`);
      pick.addEventListener('click', () => selectText(name)); row.append(pick);
    }
    $('capture-form').append(title, row);
  }
  if ($('kind').value === 'ODDS') {
    function toggleLine() {
      const numeric = !['MONEYLINE', 'THREE_WAY'].includes($('line_type').value);
      $('line').disabled = !numeric;
      if (!numeric) $('line').value = '';
      for (const key of ['outcome_3', 'odds_3']) {
        $(key).disabled = $('line_type').value !== 'THREE_WAY';
        if ($(key).disabled) $(key).value = '';
      }
    }
    $('line_type').addEventListener('change', toggleLine); toggleLine();
  }
}
async function activeSource() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url) throw new Error('Pulsa el icono de la extensión en la pestaña que quieres capturar.');
  const location = publicLocation(tab.url);
  // The full URL is used only in memory to prevent mixed-page captures. Never exported.
  return { id: tab.id, url: tab.url, origin: location.origin };
}
async function checkSource() {
  const current = await activeSource();
  if (!source || source.id !== current.id || source.url !== current.url) {
    throw new Error('La página cambió. Usa «Usar pestaña actual» para iniciar otra captura.');
  }
  return current;
}
async function selectText(name) {
  if (picking || $(name).disabled) return;
  const epoch = generation;
  try {
    const current = await checkSource(); picking = true;
    status('Haz clic en un texto público de la página. Esc cancela; caduca en 30 segundos.');
    let results;
    try { results = await chrome.scripting.executeScript({ target: { tabId: current.id }, func: pickPublicText }); }
    catch { throw new Error('Sin acceso a la pestaña. Pulsa allí el icono de la extensión y vuelve a intentarlo.'); }
    await checkSource();
    if (epoch !== generation) throw new Error('La captura cambió; vuelve a seleccionar el dato.');
    const result = results[0]?.result;
    if (!result?.text || result.origin !== source.origin) throw new Error('Selección cancelada o campo no permitido. Elige un dato público pequeño, fuera de formularios y boletas.');
    $(name).value = result.text;
    invalidate(); status('Dato seleccionado. Revísalo antes de exportar.');
  } catch (error) { status(error instanceof Error && !error.message.includes('Cannot access') ? error.message : 'Sin acceso a la pestaña. Pulsa allí el icono de la extensión y vuelve a intentarlo.'); }
  finally { picking = false; }
}
$('open').addEventListener('click', async () => {
  try { const location = publicLocation($('url').value); await chrome.tabs.create({ url: location.navigation }); status('Página abierta. Pulsa el icono de la extensión en ella y vincula la pestaña.'); }
  catch { status('No se pudo abrir. Usa una URL HTTPS de una página pública, sin credenciales.'); }
});
$('connect').addEventListener('click', async () => {
  try { source = await activeSource(); render(); $('source').textContent = source.origin; status('Página vinculada. Puedes seleccionar datos o completar los campos.'); }
  catch { status('No se pudo vincular. Abre una página pública HTTPS y pulsa el icono de la extensión en esa pestaña.'); }
});
$('kind').addEventListener('change', render);
$('capture-form').addEventListener('submit', event => event.preventDefault());
$('preview').addEventListener('click', async () => {
  try {
    await checkSource();
    if (picking) throw new Error('Termina la selección antes de preparar la captura.');
    preview = buildCapture($('kind').value, Object.fromEntries(new FormData($('capture-form'))), source.origin);
    $('json').textContent = JSON.stringify(preview, null, 2);
    $('confirmed').checked = false; $('download').disabled = true; $('review').hidden = false;
    status('Vista previa preparada. Confirma la revisión para descargar.');
  } catch (error) { invalidate(); status(error.message); }
});
$('confirmed').addEventListener('change', () => { $('download').disabled = !$('confirmed').checked || !preview; });
$('download').addEventListener('click', async () => {
  try {
    await checkSource();
    if (!preview || !$('confirmed').checked) return;
    const blob = new Blob([JSON.stringify(preview, null, 2) + '\n'], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `sports-capture-${preview.capture_id}.json`;
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    status('JSON descargado. Puedes importarlo con sports-capture import. Conserva el archivo fuera del repositorio.');
  } catch { invalidate(); status('La pestaña cambió. Vincúlala y prepara una captura nueva.'); }
});
$('reset').addEventListener('click', () => { render(); status('Formulario vacío. Prepara una nueva observación.'); });
render();
