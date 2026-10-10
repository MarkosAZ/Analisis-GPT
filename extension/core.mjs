export const SCHEMA = 'browser_capture_v1';
export const SPORTS = ['FOOTBALL', 'BASKETBALL', 'BASEBALL'];
export const STATUSES = ['SCHEDULED', 'IN_PROGRESS', 'FINISHED', 'POSTPONED', 'CANCELLED', 'ABANDONED'];
export const LINE_TYPES = ['MONEYLINE', 'THREE_WAY', 'HALF_LINE', 'INTEGER_PUSH', 'ASIAN_QUARTER'];
const privateRoute = /(?:account|login|signin|register|wallet|cashier|deposit|withdraw|betslip|my[-_]?bets|mis[-_]?apuestas|balance|saldo|cuenta|boleta|bilhete|cupom)/i;

export function publicLocation(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password ||
      privateRoute.test(decodeURIComponent(url.pathname)) || !url.hostname.includes('.')) {
    throw new Error('Usa una página HTTPS de calendario o cuotas públicas.');
  }
  return { origin: url.origin, navigation: `${url.origin}${url.pathname}` };
}

export function text(value, name) {
  if (typeof value !== 'string' || value.length < 1 || value.length > 100 ||
      value.trim() !== value || /[<>@\x00-\x1f\x7f]|:\/\/|bearer\s|gh[pousr]_/i.test(value)) {
    throw new Error(`Revisa ${name}: texto público de 1 a 100 caracteres.`);
  }
  return value;
}

export function identifier(value, name) {
  if (!/^[A-Za-z0-9_.:-]{1,100}$/.test(text(value, name))) {
    throw new Error(`Revisa ${name}: usa un identificador público estable, sin URL.`);
  }
  return value;
}

export function timestamp(value, name) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) ||
      !Number.isFinite(Date.parse(value))) {
    throw new Error(`Revisa ${name}: fecha ISO con zona, por ejemplo 2030-06-15T20:00:00-05:00.`);
  }
  const [year, month, day, hour, minute, second] = value.match(/\d+/g).slice(0, 6).map(Number);
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (date.getUTCFullYear() !== year || date.getUTCMonth() + 1 !== month || date.getUTCDate() !== day ||
      hour > 23 || minute > 59 || second > 59) throw new Error(`Revisa ${name}: fecha inexistente.`);
  return value;
}

function choice(value, options, name) {
  if (!options.includes(value)) throw new Error(`Revisa ${name}.`);
  return value;
}

export function decimal(value, name, odds = false) {
  if (typeof value !== 'string' || !/^-?\d{1,6}(?:\.\d{1,4})?$/.test(value) ||
      (odds && Number(value) <= 1)) {
    throw new Error(`Revisa ${name}: decimal con punto${odds ? ', mayor que 1' : ''}.`);
  }
  return value;
}

export function buildCapture(kind, values, origin, now = new Date(), captureId = crypto.randomUUID()) {
  if (publicLocation(origin).origin !== origin) throw new Error('Origen público inválido.');
  const record = {
    event_id: identifier(values.event_id, 'ID del evento'),
    sport: choice(values.sport, SPORTS, 'deporte'),
  };
  if (kind === 'CALENDAR') {
    for (const entity of ['competition', 'home', 'away']) {
      record[`${entity}_id`] = identifier(values[`${entity}_id`], `ID ${entity}`);
      record[`${entity}_name`] = text(values[`${entity}_name`], `nombre ${entity}`);
    }
    if (record.home_id === record.away_id) throw new Error('Local y visitante deben ser distintos.');
    record.scheduled_start_at = timestamp(values.scheduled_start_at, 'inicio programado');
    record.status = choice(values.status, STATUSES, 'estado');
    record.actual_start_at = values.actual_start_at ? timestamp(values.actual_start_at, 'inicio real') : null;
    if (record.status === 'FINISHED' && !record.actual_start_at) throw new Error('Un partido finalizado requiere inicio real.');
    if (record.actual_start_at && (Date.parse(record.actual_start_at) > now.getTime() || record.status === 'SCHEDULED')) {
      throw new Error('El inicio real contradice el estado o está en el futuro.');
    }
  } else if (kind === 'ODDS') {
    record.bookmaker = text(values.bookmaker, 'casa');
    record.market = identifier(values.market, 'mercado');
    record.period = identifier(values.period, 'periodo');
    record.line_type = choice(values.line_type, LINE_TYPES, 'tipo de línea');
    record.line = ['MONEYLINE', 'THREE_WAY'].includes(record.line_type) ? null : decimal(values.line, 'línea');
    if (record.line !== null) {
      const quarters = Math.round(Math.abs(Number(record.line)) * 10000) % 10000;
      const valid = { HALF_LINE: [5000], INTEGER_PUSH: [0], ASIAN_QUARTER: [2500, 7500] };
      if (!valid[record.line_type].includes(quarters)) throw new Error('La línea no coincide con su tipo.');
    }
    const count = record.line_type === 'THREE_WAY' ? 3 : 2;
    record.outcomes = Array.from({ length: count }, (_, i) => ({
      code: identifier(values[`outcome_${i + 1}`], `resultado ${i + 1}`),
      decimal_odds: decimal(values[`odds_${i + 1}`], `cuota ${i + 1}`, true),
    }));
    if (new Set(record.outcomes.map(item => item.code)).size !== count) throw new Error('Los resultados deben ser distintos.');
  } else throw new Error('Tipo de captura inválido.');
  return {
    schema_version: SCHEMA,
    capture_id: captureId,
    capture_method: 'MANUAL_REVIEW',
    captured_at: now.toISOString(),
    source_origin: origin,
    kind,
    record,
  };
}
