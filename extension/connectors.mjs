// Browser-side source adapters. Public protocol shapes inspected in Analisis-BDP
// 7b0dcd97; this implementation keeps our own bounded, versioned capture contract.
import { buildCapture, publicLocation } from './core.mjs';
import { SOURCES } from './sources.mjs';
import { collectBetano } from './source-page.mjs';
import { sofaRows, flashRows, betanoRows, totalRows, totalEventIds } from './source-parsers.mjs';

export const CONNECTORS = {
  sofascore: { reader: 'sofascore_calendar_v1', kind: 'CALENDAR', hosts: ['https://www.sofascore.com/*'], detail: 'Calendario de fútbol de hoy · API pública' },
  betano_pe: { reader: 'betano_public_v1', kind: 'ODDS', hosts: ['https://www.betano.pe/*'], detail: 'Cuotas de fútbol disponibles en la página' },
  apuesta_total: { reader: 'apuesta_total_public_v1', kind: 'ODDS', hosts: ['https://www.apuestatotal.com/*', 'https://prod20392.kmianko.com/*'], detail: 'Cuotas de fútbol · proveedor público del sportsbook' },
  flashscore_pe: { reader: 'flashscore_calendar_v1', kind: 'CALENDAR', hosts: ['https://www.flashscore.pe/*', 'https://global.flashscore.ninja/*'], detail: 'Calendario de fútbol de hoy · feed público' },
};
export const nativeProfile = id => {
  const source = SOURCES.find(item => item.id === id); const adapter = CONNECTORS[id];
  if (!source || !adapter) throw new Error('UNSUPPORTED_SOURCE');
  return { ...source, url: id === 'betano_pe' ? 'https://www.betano.pe/sport/futbol/' : source.url,
    version: '1', reader: adapter.reader, kind: adapter.kind, sport: 'FOOTBALL' };
};
export function isNative(source) { return CONNECTORS[source?.id]?.reader === source?.reader; }
export function nativeLanding(source, value) {
  try {
    const url = new URL(value);
    if (url.origin !== new URL(source.url).origin || url.search || url.hash || publicLocation(value).navigation !== value) return false;
    const paths = {
      sofascore: /^\/(?:[a-z]{2}\/)?(?:football\/?)?$/,
      betano_pe: /^\/sport\/futbol\/$/,
      apuesta_total: /^\/apuestas-deportivas\/?$/,
      flashscore_pe: /^\/(?:futbol\/)?$/,
    };
    return Boolean(paths[source.id]?.test(url.pathname));
  } catch { return false; }
}
export function validateNative(source) {
  const expected = nativeProfile(source.id);
  if (Object.keys(source).length !== Object.keys(expected).length ||
      Object.entries(expected).some(([key, value]) => source[key] !== value)) throw new Error('INVALID_CONFIG');
}
export const limaDay = time => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima' }).format(new Date(time));

const ENDPOINTS = [
  /^https:\/\/www\.sofascore\.com\/api\/v1\/sport\/football\/scheduled-events\/\d{4}-\d{2}-\d{2}$/,
  /^https:\/\/global\.flashscore\.ninja\/203\/x\/feed\/f_1_0_-5_es-pe_1$/,
  /^https:\/\/prod20392\.kmianko\.com\/api\/pulse\/snapshot\/events\?lang=ES-PE&t=hPNl$/,
  /^https:\/\/prod20392\.kmianko\.com\/api\/eventlist\/eu\/markets\/all\?markets=[A-Za-z0-9%_.-]+$/,
];
// Only fixed public GETs. The sportsbook may use its existing anonymous browser
// session; cookie values and authorization headers are never read or exported.
export async function publicResponse(url, { fetcher = fetch, text = false, signal } = {}) {
  if (!ENDPOINTS.some(pattern => pattern.test(url))) throw new Error('INVALID_ENDPOINT');
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) throw new Error('CANCELLED');
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, 12000);
  try {
    // x-fsign is the public feed protocol constant in the reference, not a user credential.
    const headers = url.startsWith('https://global.flashscore.ninja/') ? { 'x-fsign': 'SW9D1eZo' } : {};
    const credentials = url.startsWith('https://prod20392.kmianko.com/') ? 'include' : 'omit';
    const response = await fetcher(url, { headers, credentials, redirect: 'error', cache: 'no-store', signal: controller.signal });
    if ([401, 403, 429].includes(response.status)) throw new Error(`HTTP_${response.status}`);
    if (!response.ok) throw new Error('SOURCE_HTTP_ERROR');
    if (Number(response.headers.get('content-length')) > 2 * 1024 * 1024) throw new Error('RESPONSE_LIMIT');
    const reader = response.body?.getReader();
    if (!reader) throw new Error('SCHEMA_CHANGED');
    let size = 0; const decoder = new TextDecoder(); let body = '';
    try {
      while (true) {
        const part = await reader.read(); if (part.done) break;
        size += part.value.byteLength;
        if (size > 2 * 1024 * 1024) { await reader.cancel(); throw new Error('RESPONSE_LIMIT'); }
        body += decoder.decode(part.value, { stream: true });
      }
      body += decoder.decode();
    } finally { reader.releaseLock(); }
    if (/^\s*</.test(body)) throw new Error('ACCESS_RESTRICTED');
    try { return text ? body : JSON.parse(body); } catch { throw new Error('SCHEMA_CHANGED'); }
  } catch (error) {
    if (controller.signal.aborted) throw new Error(signal?.aborted ? 'CANCELLED' : 'TIMEOUT');
    if (['HTTP_401', 'HTTP_403', 'HTTP_429', 'SOURCE_HTTP_ERROR', 'RESPONSE_LIMIT', 'SCHEMA_CHANGED', 'ACCESS_RESTRICTED'].includes(error.message)) throw error;
    throw new Error('NETWORK_ERROR');
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}

export async function readConnector(source, api, tabId, { now = () => Date.now(), fetcher = fetch, signal } = {}) {
  validateNative(source);
  const day = limaDay(now()); const options = { fetcher, signal };
  let parsed;
  if (source.id === 'sofascore') {
    const next = new Date(`${day}T12:00:00Z`); next.setUTCDate(next.getUTCDate() + 1);
    const events = [];
    // Two UTC days cover one complete Lima day. No historical availability is inferred.
    for (const date of [day, next.toISOString().slice(0, 10)]) {
      const data = await publicResponse(`https://www.sofascore.com/api/v1/sport/football/scheduled-events/${date}`, options);
      if (!Array.isArray(data.events)) throw new Error('SCHEMA_CHANGED');
      events.push(...data.events);
    }
    parsed = sofaRows(events, day);
  } else if (source.id === 'flashscore_pe') {
    parsed = flashRows(await publicResponse('https://global.flashscore.ninja/203/x/feed/f_1_0_-5_es-pe_1', { ...options, text: true }), day);
  } else if (source.id === 'betano_pe') {
    const result = await api.scripting.executeScript({ target: { tabId, frameIds: [0] }, world: 'MAIN', func: collectBetano, args: [] });
    const projection = result[0]?.result;
    if (projection?.error) throw new Error(projection.error);
    if (!Array.isArray(projection?.events)) throw new Error('SCHEMA_CHANGED');
    if (!projection.events.length) return { error: 'NOT_READY' };
    parsed = betanoRows(projection.events);
  } else {
    const events = await publicResponse('https://prod20392.kmianko.com/api/pulse/snapshot/events?lang=ES-PE&t=hPNl', options);
    const ids = totalEventIds(events, day);
    if (!ids.length) throw new Error('NO_PUBLIC_DATA');
    // One bounded request: at most ten matches, two known market types, no enumeration.
    const query = encodeURIComponent(`${ids.join('|')}:ML0|OU0`);
    const markets = await publicResponse(`https://prod20392.kmianko.com/api/eventlist/eu/markets/all?markets=${query}`, options);
    parsed = totalRows(markets, ids);
  }
  if (signal?.aborted) throw new Error('CANCELLED');
  const observed_at = new Date(now()).toISOString();
  const records = []; let skipped = parsed.skipped;
  for (const row of parsed.records) {
    try { buildCapture(source.kind, row, new URL(source.url).origin, new Date(observed_at)); records.push(row); }
    catch { skipped++; }
  }
  if (!records.length) throw new Error(skipped ? 'SCHEMA_CHANGED' : 'NO_PUBLIC_DATA');
  return { records: records.slice(0, 50), observed_at, origin: new URL(source.url).origin,
    skipped, truncated: Math.max(0, records.length - 50), day };
}
