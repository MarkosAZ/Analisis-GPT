import test from 'node:test';
import assert from 'node:assert/strict';
import { CONNECTORS, nativeLanding, nativeProfile, publicResponse, readConnector } from '../../extension/connectors.mjs';
import { automaticCapture, originsFor, profileHash, validateConfig } from '../../extension/scan-contract.mjs';
import { sofaRows, flashRows, betanoRows, totalRows, totalEventIds } from '../../extension/source-parsers.mjs';

const event = (id = 101, start = '2030-06-16T02:00:00Z') => ({ id, startTimestamp: Date.parse(start) / 1000, status: { type: 'notstarted' },
  tournament: { id: 5, name: 'Fixture League' }, homeTeam: { id: 7, name: 'Fixture Home' }, awayTeam: { id: 8, name: 'Fixture Away' } });
const total = line => ({ name: 'Total de goles', selections: [{ name: `Más de ${line}`, price: '1.95' }, { name: `Menos de ${line}`, price: '2.05' }] });
const response = data => new Response(typeof data === 'string' ? data : JSON.stringify(data), { status: 200 });

test('included connectors are fixed, versioned and request only their public destinations', () => {
  const sources = Object.keys(CONNECTORS).map(nativeProfile);
  validateConfig({ schema_version: 'browser_scan_config_v1', sources });
  assert.equal(sources.length, 4); assert.throws(() => nativeProfile('te_apuesto'));
  assert.equal(nativeLanding(nativeProfile('sofascore'), 'https://www.sofascore.com/es/'), true);
  for (const url of ['https://www.sofascore.com/account', 'https://www.sofascore.com/?token=x', 'https://www.sofascore.com.evil.example/', 'https://other.example/']) assert.equal(nativeLanding(nativeProfile('sofascore'), url), false);
  assert.deepEqual(originsFor({ sources: [nativeProfile('apuesta_total')] }), ['https://www.apuestatotal.com/*', 'https://prod20392.kmianko.com/*']);
  for (const patch of [{ url: 'https://evil.example/' }, { sport: 'BASKETBALL' }, { version: '999' }, { script: 'fetch("private")' }]) {
    assert.throws(() => validateConfig({ schema_version: 'browser_scan_config_v1', sources: [{ ...nativeProfile('sofascore'), ...patch }] }));
  }
});
test('SofaScore honors the Lima boundary, uses stable identities and never invents an actual start', () => {
  const finished = { ...event(102), status: { type: 'finished' } };
  const missing = event(104); delete missing.homeTeam.id;
  const result = sofaRows([event(), event(103, '2030-06-16T06:00:00Z'), finished, missing], '2030-06-15');
  assert.equal(result.records.length, 1); assert.equal(result.records[0].event_id, '101');
  assert.equal(result.skipped, 1); assert.equal(result.records[0].actual_start_at, undefined);
  assert.throws(() => sofaRows([event(), { ...event(), homeTeam: { id: 9, name: 'Conflicting team' } }], '2030-06-15'), /AMBIGUOUS_SOURCE/);
});
test('Flashscore preserves postponed and cancelled states and rejects missing stable IDs', () => {
  const timestamp = Date.parse('2030-06-15T18:00:00Z') / 1000;
  const fields = `AD÷${timestamp}¬PX÷home-1¬PY÷away-2¬AE÷Fixture Home¬AF÷Fixture Away`;
  const feed = `ZA÷Perú: Fixture League¬ZEE÷league-1~AA÷event-1¬AB÷1¬${fields}~AA÷event-2¬AB÷1¬AC÷4¬${fields}~AA÷event-3¬AB÷1¬AC÷5¬${fields}~AA÷event-4¬AB÷3¬${fields}~AA÷event-5¬AB÷1¬AD÷${timestamp}`;
  const parsed = flashRows(feed, '2030-06-15');
  assert.deepEqual(parsed.records.map(row => row.status), ['SCHEDULED', 'POSTPONED', 'CANCELLED']); assert.equal(parsed.skipped, 1);
  assert.throws(() => flashRows('<html>Account blocked</html>', '2030-06-15'), /SCHEMA_CHANGED/);
});
test('odds readers keep half, integer and quarter lines without combining different markets', () => {
  for (const [line, kind] of [['2.5', 'HALF_LINE'], ['3', 'INTEGER_PUSH'], ['2.25', 'ASIAN_QUARTER']]) {
    const parsed = betanoRows([{ id: 'event-1', markets: [total(line)] }]);
    assert.equal(parsed.records[0].line_type, kind); assert.equal(parsed.records[0].line, line);
    assert.equal(parsed.records[0].outcome_1, 'OVER'); assert.equal(parsed.records[0].odds_1, '1.95');
  }
  const mixed = total('2.5'); mixed.selections[1].name = 'Menos de 3.5';
  const half = { ...total('2.5'), name: 'Total de goles primer tiempo' };
  const scoped = { ...total('2.5'), period: 'FIRST_HALF' };
  assert.deepEqual(betanoRows([{ id: 'e', markets: [mixed, half, scoped] }]), { records: [], skipped: 3 });
  const conflict = total('2.5'); conflict.selections[0].price = '2.50';
  assert.throws(() => betanoRows([{ id: 'e', markets: [total('2.5'), conflict] }]), /AMBIGUOUS_SOURCE/);
});
test('three-way and yes/no outcomes remain complete and identifiable', () => {
  const rows = betanoRows([{ id: 'e', markets: [
    { name: '1X2', selections: [{ name: '1', price: 2 }, { name: 'X', price: 3 }, { name: '2', price: 4 }] },
    { name: 'Ambos anotan', selections: [{ name: 'Sí', price: 1.8 }, { name: 'No', price: 2 }] },
  ] }]).records;
  assert.equal(rows[0].line_type, 'THREE_WAY'); assert.equal(rows[0].outcome_2, 'DRAW');
  assert.equal(rows[1].outcome_1, 'YES'); assert.equal(rows[1].line_type, 'MONEYLINE');
  const named = betanoRows([{ id: 'named-event', home_name: 'Fixture Home', away_name: 'Fixture Away', markets: [{ name: 'Resultado del partido', selections: [
    { name: 'Fixture Home', price: 2 }, { name: 'Empate', price: 3 }, { name: 'Fixture Away', price: 4 },
  ] }] }]);
  assert.equal(named.records[0].outcome_1, 'HOME'); assert.equal(named.records[0].outcome_3, 'AWAY');
});
test('Apuesta Total queries only ten identified fixtures, excluding live and suspended events', () => {
  const events = Array.from({ length: 20 }, (_, index) => ({ _id: `event-${index}`, Type: 'Fixture', SportName: 'Fútbol', StartEventDate: Date.parse('2030-06-15T20:00:00Z') }));
  events[0].IsLive = true; events[1].IsSuspended = true;
  const ids = totalEventIds(events, '2030-06-15'); assert.equal(ids.length, 10); assert.equal(ids[0], 'event-2');
  const market = { EventId: 'event-2', MarketType: { _id: 'OU0' }, Selections: [
    { Name: 'Más', QAParam1: 2.5, DisplayOdds: { Decimal: 1.9 } }, { Name: 'Menos', QAParam1: 2.5, DisplayOdds: { Decimal: 2.1 } },
  ] };
  const parsed = totalRows([market, { ...market, EventId: 'different-event' }], ids);
  assert.equal(parsed.records.length, 1); assert.equal(parsed.records[0].event_id, 'event-2');
  market.Selections[0].IsDisabled = true; assert.equal(totalRows([market], ids).records.length, 0);
});
test('network boundary excludes cookies, arbitrary hosts, redirects and response bodies from errors', async () => {
  const url = 'https://www.sofascore.com/api/v1/sport/football/scheduled-events/2030-06-15';
  let calls = 0;
  for (const status of [401, 403, 429]) {
    await assert.rejects(publicResponse(url, { fetcher: async (target, options) => {
      calls++; assert.equal(target, url); assert.equal(options.credentials, 'omit'); assert.equal(options.redirect, 'error');
      assert.deepEqual(options.headers, {}); return new Response('SECRET BODY', { status });
    } }), new RegExp(`^Error: HTTP_${status}$`));
  }
  assert.equal(calls, 3);
  for (const target of ['https://evil.example/', `${url}?token=private`, 'http://127.0.0.1/']) {
    await assert.rejects(publicResponse(target, { fetcher: () => { throw new Error('MUST_NOT_CALL'); } }), /INVALID_ENDPOINT/);
  }
  await assert.rejects(publicResponse(url, { fetcher: async () => response('<html>Login</html>') }), /ACCESS_RESTRICTED/);
  await assert.rejects(publicResponse(url, { fetcher: async () => response('x'.repeat(2 * 1024 * 1024 + 1)) }), /RESPONSE_LIMIT/);
  await publicResponse('https://prod20392.kmianko.com/api/pulse/snapshot/events?lang=ES-PE&t=hPNl', { fetcher: async (_url, options) => {
    assert.equal(options.credentials, 'include'); assert.deepEqual(options.headers, {}); return response([]);
  } });
});
test('cancellation aborts source requests rather than starting a fallback', async () => {
  const controller = new AbortController(); let calls = 0;
  const task = publicResponse('https://global.flashscore.ninja/203/x/feed/f_1_0_-5_es-pe_1', { signal: controller.signal,
    fetcher: (_url, options) => new Promise((_resolve, reject) => { calls++; options.signal.addEventListener('abort', () => reject(new Error('Abort'))); }) });
  controller.abort(); await assert.rejects(task, /CANCELLED/); assert.equal(calls, 1);
});
test('native scan reads both UTC dates and creates a distinct source capture version', async () => {
  const urls = []; const source = nativeProfile('sofascore');
  const read = await readConnector(source, {}, 1, { now: () => Date.parse('2030-06-15T12:00:00Z'), fetcher: async url => {
    urls.push(url); return response({ events: url.endsWith('2030-06-16') ? [event()] : [] });
  } });
  assert.equal(urls.length, 2); assert.ok(urls[1].endsWith('/2030-06-16'));
  const capture = automaticCapture(source, read.records[0], read.observed_at, crypto.randomUUID(), await profileHash(source));
  assert.equal(capture.schema_version, 'browser_capture_v3'); assert.equal(capture.capture_method, 'AUTOMATIC_SOURCE');
  assert.equal(capture.reader_version, 'sofascore_calendar_v1'); assert.equal(capture.source_origin, 'https://www.sofascore.com');
});
