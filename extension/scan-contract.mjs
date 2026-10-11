import { publicLocation, text, identifier, buildCapture } from './core.mjs';

export const READER = 'dom_fields_v1';
export const MAX_SOURCES = 10;
export const MAX_ROWS = 50;
export const MAX_CAPTURES = 200;
export const MAX_CONFIG_BYTES = 65536;
export const TERMINAL = ['COMPLETED', 'COMPLETED_WITH_ERRORS', 'CANCELLED', 'INTERRUPTED'];
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export function exact(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).length !== keys.length || !keys.every(key => Object.hasOwn(value, key))) throw new Error('INVALID_CONFIG');
}
export function projectPage(value) {
  try {
    const url = new URL(value);
    if (url.username || url.password || url.search) return false;
    if (url.origin === 'https://markosaz.github.io') return ['/Analisis-GPT/', '/Analisis-GPT/index.html'].includes(url.pathname);
    return ['http://127.0.0.1:8000', 'http://localhost:8000'].includes(url.origin) && ['/', '/index.html'].includes(url.pathname);
  } catch { return false; }
}
export function scanLocation(value) {
  const location = publicLocation(value);
  const url = new URL(value);
  const host = url.hostname.toLowerCase();
  // Scanning never opens local/private network destinations, credentials or token queries.
  if (url.search || url.hash || (url.port && url.port !== '443') ||
      /^[\d.]+$/.test(host) || host.includes(':') || /(?:^|\.)(?:localhost|local|internal|lan)$/.test(host) ||
      location.navigation !== value) throw new Error('INVALID_SOURCE_URL');
  return location;
}
const calendar = ['event_id', 'sport', 'competition_id', 'competition_name', 'home_id', 'home_name', 'away_id', 'away_name', 'scheduled_start_at', 'status'];
const odds = ['event_id', 'sport', 'bookmaker', 'market', 'period', 'line_type', 'outcome_1', 'odds_1', 'outcome_2', 'odds_2'];
const literals = new Set(['sport', 'bookmaker', 'market', 'period', 'line_type', 'outcome_1', 'outcome_2', 'outcome_3']);
function selector(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 200 || /[\x00-\x1f\x7f]/.test(value)) throw new Error('INVALID_SELECTOR');
  return value;
}
export function validateConfig(config) {
  exact(config, ['schema_version', 'sources']);
  if (config.schema_version !== 'browser_scan_config_v1' || !Array.isArray(config.sources) || config.sources.length > MAX_SOURCES ||
      new TextEncoder().encode(JSON.stringify(config)).length > MAX_CONFIG_BYTES) throw new Error('INVALID_CONFIG');
  const ids = new Set();
  for (const source of config.sources) {
    exact(source, ['id', 'version', 'label', 'url', 'reader', 'kind', 'row_selector', 'fields']);
    identifier(source.id, 'perfil'); identifier(source.version, 'versión'); text(source.label, 'fuente');
    if (ids.has(source.id) || source.reader !== READER || !['CALENDAR', 'ODDS'].includes(source.kind)) throw new Error('INVALID_CONFIG');
    ids.add(source.id); scanLocation(source.url); selector(source.row_selector);
    const required = source.kind === 'CALENDAR' ? calendar : odds;
    const allowed = new Set([...required, ...(source.kind === 'CALENDAR' ? ['actual_start_at'] : ['line', 'outcome_3', 'odds_3'])]);
    if (!source.fields || typeof source.fields !== 'object' || Array.isArray(source.fields) ||
        !required.every(key => Object.hasOwn(source.fields, key)) || Object.keys(source.fields).some(key => !allowed.has(key))) throw new Error('INVALID_FIELDS');
    for (const [key, field] of Object.entries(source.fields)) {
      if (field && Object.hasOwn(field, 'value')) {
        exact(field, ['value']);
        if (!literals.has(key)) throw new Error('OBSERVED_FIELD_REQUIRED');
        text(field.value, key);
      } else {
        exact(field, ['selector', 'attribute']); selector(field.selector);
        if (field.attribute !== null && (typeof field.attribute !== 'string' || !/^(?:datetime|data-[a-z][a-z0-9-]{0,50})$/.test(field.attribute))) throw new Error('INVALID_ATTRIBUTE');
      }
    }
  }
  return config;
}
export const originsFor = config => [...new Set(config.sources.map(source => `${scanLocation(source.url).origin}/*`))];
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}
export async function profileHash(source) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(source)));
  return [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}
export function automaticCapture(source, row, observedAt, scanId, hash) {
  const capture = buildCapture(source.kind, row, scanLocation(source.url).origin, new Date(observedAt));
  return { ...capture, schema_version: 'browser_capture_v2', capture_method: 'AUTOMATIC_DOM',
    scan_id: scanId, reader_version: READER, profile_id: source.id, profile_version: source.version, profile_hash: hash };
}
