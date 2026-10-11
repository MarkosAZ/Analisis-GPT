export const SCHEMA = 'public_calendar_v1';
export const TIMEZONE = 'America/Lima';
export const MAX_BYTES = 2 * 1024 * 1024;
export const SPORTS = { FOOTBALL: 'Fútbol', BASKETBALL: 'Baloncesto', BASEBALL: 'Béisbol' };
export const STATUS = { SCHEDULED: 'Programado', TRACKING: 'En seguimiento', LOCKED: 'En juego', FINALIZED: 'Finalizado', POSTPONED: 'Aplazado', CANCELLED: 'Cancelado', ABANDONED: 'Abandonado' };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const TOP_KEYS = ['schema_version', 'data_kind', 'generated_at', 'display_timezone', 'cycles'];
const CYCLE_KEYS = ['event_id', 'event_cycle_id', 'cycle_number', 'previous_cycle_id', 'sport', 'competition', 'home', 'away', 'scheduled_start_at', 'actual_start_at', 'status', 'tracking_status', 'last_observed_at'];
function exactKeys(value, expected) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== expected.length ||
      !expected.every(key => Object.hasOwn(value, key))) throw new Error('El archivo contiene campos ajenos al calendario público.');
}
function timestamp(value, nullable = false) {
  if (value === null && nullable) return;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) {
    throw new Error('El calendario contiene fechas inválidas o sin zona horaria.');
  }
  const [year, month, day, hour, minute, second] = value.match(/\d+/g).slice(0, 6).map(Number);
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (date.getUTCFullYear() !== year || date.getUTCMonth() + 1 !== month || date.getUTCDate() !== day || hour > 23 || minute > 59 || second > 59) throw new Error('El calendario contiene una fecha inexistente.');
}
export function validateSnapshot(data) {
  exactKeys(data, TOP_KEYS);
  if (data.schema_version !== SCHEMA || !['PUBLIC', 'SYNTHETIC'].includes(data.data_kind) || data.display_timezone !== TIMEZONE || !Array.isArray(data.cycles) || data.cycles.length > 5000) throw new Error('Formato de calendario público no compatible.');
  timestamp(data.generated_at, true);
  if (data.cycles.length && !data.generated_at) throw new Error('Falta la fecha de publicación.');
  const cycles = new Map();
  const numbers = new Set();
  for (const item of data.cycles) {
    exactKeys(item, CYCLE_KEYS);
    if (!UUID.test(item.event_id) || !UUID.test(item.event_cycle_id) || cycles.has(item.event_cycle_id) ||
        !Number.isInteger(item.cycle_number) || item.cycle_number < 1 ||
        !Object.hasOwn(SPORTS, item.sport) || !Object.hasOwn(STATUS, item.status) ||
        ![null, 'ACTIVE', 'PAUSED', 'CLOSED'].includes(item.tracking_status)) throw new Error('Identidad o estado de partido inválidos.');
    for (const name of ['competition', 'home', 'away']) {
      if (typeof item[name] !== 'string' || !item[name].trim() || item[name].length > 100 || /[<>@\x00-\x1f\x7f]|:\/\//.test(item[name])) throw new Error('El calendario contiene texto no admitido.');
    }
    timestamp(item.scheduled_start_at);
    timestamp(item.actual_start_at, true);
    timestamp(item.last_observed_at);
    if (Date.parse(item.last_observed_at) > Date.parse(data.generated_at)) throw new Error('La observación es posterior a la publicación.');
    const number = `${item.event_id}:${item.cycle_number}`;
    if (numbers.has(number)) throw new Error('Número de ciclo duplicado.');
    numbers.add(number);
    cycles.set(item.event_cycle_id, item);
  }
  for (const item of data.cycles) {
    if (item.cycle_number === 1) {
      if (item.previous_cycle_id !== null) throw new Error('El primer ciclo no puede tener predecesor.');
    } else {
      const previous = cycles.get(item.previous_cycle_id);
      if (!previous || previous.event_id !== item.event_id || previous.cycle_number + 1 !== item.cycle_number || previous.status !== 'POSTPONED') throw new Error('La cadena histórica de ciclos está incompleta.');
    }
  }
  return data;
}
export function localDay(value) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(value));
  const part = type => parts.find(item => item.type === type).value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
export function dayTarget(filter, now = new Date()) {
  return filter === 'TODAY' ? localDay(now) : localDay(new Date(now.getTime() + 86400000));
}
export function latestCycles(cycles) {
  const latest = new Map();
  for (const cycle of cycles) if (!latest.has(cycle.event_id) || latest.get(cycle.event_id).cycle_number < cycle.cycle_number) latest.set(cycle.event_id, cycle);
  return [...latest.values()];
}
export function filterCycles(data, { view = 'partidos', sport = 'ALL', search = '', date = 'ALL' } = {}, now = new Date()) {
  const query = search.toLocaleLowerCase('es').trim();
  let cycles = view === 'historial' ? data.cycles : latestCycles(data.cycles);
  if (view === 'seguimiento') cycles = cycles.filter(item => ['ACTIVE', 'PAUSED'].includes(item.tracking_status));
  return cycles.filter(item => (sport === 'ALL' || item.sport === sport) &&
    (!query || `${item.home} ${item.away} ${item.competition}`.toLocaleLowerCase('es').includes(query)) &&
    (date === 'ALL' || localDay(item.scheduled_start_at) === dayTarget(date, now)))
    .sort((a, b) => Date.parse(a.scheduled_start_at) - Date.parse(b.scheduled_start_at) || a.event_cycle_id.localeCompare(b.event_cycle_id));
}
