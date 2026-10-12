import test from 'node:test';
import assert from 'node:assert/strict';
import { Scanner } from '../../extension/scanner.mjs';
import { projectPage, scanLocation, validateConfig, profileHash } from '../../extension/scan-contract.mjs';
import { SOURCES } from '../../extension/sources.mjs';
import { nativeProfile } from '../../extension/connectors.mjs';

const values = { event_id: 'event-1', sport: 'FOOTBALL', bookmaker: 'Fixture Book', market: 'TOTAL_GOALS', period: 'FULL_TIME', line_type: 'HALF_LINE', line: '2.5', outcome_1: 'OVER', odds_1: '1.9', outcome_2: 'UNDER', odds_2: '2.0' };
export const profile = () => ({ id: 'fixture', version: '1', label: 'Public fixture', url: 'https://fixture.example/markets', reader: 'dom_fields_v1', kind: 'ODDS', row_selector: '.market', fields: Object.fromEntries(Object.keys(values).map(key => [key, { selector: `.${key}`, attribute: null }])) });
function setup(profiles = [profile()], initial = {}) {
  let time = Date.parse('2030-06-15T10:00:00Z');
  let next = 1;
  const tabs = new Map(); const opened = []; const closed = [];
  const local = { scanConfig: { schema_version: 'browser_scan_config_v1', sources: profiles } };
  const session = structuredClone(initial);
  const storage = bag => ({ get: async () => structuredClone(bag), set: async value => Object.assign(bag, structuredClone(value)) });
  const api = {
    storage: { local: storage(local), session: storage(session) },
    permissions: { contains: async () => true },
    tabs: {
      create: async options => { const tab = { id: next++, url: options.url, status: 'complete' }; tabs.set(tab.id, tab); opened.push(options); return tab; },
      get: async id => { if (!tabs.has(id)) throw new Error('MISSING'); return tabs.get(id); },
      remove: async id => { closed.push(id); tabs.delete(id); },
    },
    scripting: { executeScript: async options => [{ frameId: 0, result: { records: [values], observed_at: new Date(time).toISOString(), origin: new URL(options.args[0].url).origin } }] },
  };
  const options = { now: () => time, sleep: async ms => { time += ms; } };
  const scanner = new Scanner(api, options);
  return { scanner, api, session, opened, closed, tabs, options, advance: ms => { time += ms; } };
}
test('only exact project origins, paths and local port can issue commands', () => {
  for (const url of ['https://markosaz.github.io/Analisis-GPT/#extension', 'http://127.0.0.1:8000/', 'http://localhost:8000/index.html']) assert.equal(projectPage(url), true);
  for (const url of ['https://evil.example/', 'https://markosaz.github.io/other/', 'https://markosaz.github.io/Analisis-GPT/fake.html', 'http://localhost:8001/', 'https://markosaz.github.io/Analisis-GPT/?token=x']) assert.equal(projectPage(url), false);
});
test('configured readers reject credentials, private destinations, code and non-public fields', () => {
  for (const url of ['https://fixture.example/market?token=x', 'https://fixture.example/account', 'https://127.0.0.1/', 'https://service.local/', 'https://fixture.example:9999/', 'https://fixture.example/#secret']) assert.throws(() => scanLocation(url));
  const config = () => ({ schema_version: 'browser_scan_config_v1', sources: [profile()] });
  validateConfig(config());
  for (const change of [source => source.fields.odds_1 = { value: '2.2' }, source => source.fields.token = { selector: '.token', attribute: null }, source => source.fields.event_id.attribute = 'value', source => source.script = 'alert(1)']) {
    const invalid = config(); change(invalid.sources[0]); assert.throws(() => validateConfig(invalid));
  }
});
test('profile hashes are deterministic and change with selectors or versions', async () => {
  const first = profile(); const reordered = Object.fromEntries(Object.entries(first).reverse());
  assert.equal(await profileHash(first), await profileHash(reordered));
  reordered.version = '2'; assert.notEqual(await profileHash(first), await profileHash(reordered));
});
test('sequential automatic scan closes only its tabs and exports truthful provenance', async () => {
  const second = { ...profile(), id: 'second', url: 'https://other.example/markets' };
  const s = setup([profile(), second]);
  const request = crypto.randomUUID(); await s.scanner.start(request, 999); await s.scanner.task;
  const result = await s.scanner.results();
  assert.equal(result.status, 'COMPLETED'); assert.equal(result.captures.length, 2);
  assert.deepEqual(s.closed, [1, 2]); assert.equal(s.opened.every(tab => tab.active === false), true);
  const capture = result.captures[0];
  assert.equal(capture.capture_method, 'AUTOMATIC_DOM'); assert.equal(capture.schema_version, 'browser_capture_v2');
  assert.equal(capture.scan_id, request); assert.match(capture.profile_hash, /^[a-f0-9]{64}$/);
  assert.equal(capture.record.outcomes[0].decimal_odds, '1.9');
  assert.equal(JSON.stringify(result).includes('/markets'), false);
  await s.scanner.start(request, 999); assert.equal(s.opened.length, 2);
  await assert.rejects(s.scanner.start(crypto.randomUUID(), 999), /COOLDOWN/);
  s.advance(60000); await s.scanner.start(crypto.randomUUID(), 999); await s.scanner.task;
  assert.notEqual((await s.scanner.results()).captures[0].capture_id, capture.capture_id);
});
test('missing grants open no pages; duplicates cannot create parallel scans', async () => {
  const s = setup(); s.api.permissions.contains = async () => false;
  await assert.rejects(s.scanner.start(crypto.randomUUID(), 999), /NEEDS_PERMISSIONS/); assert.equal(s.opened.length, 0);
  let release; s.api.permissions.contains = () => new Promise(resolve => { release = resolve; });
  const first = s.scanner.start(crypto.randomUUID(), 999); await new Promise(setImmediate);
  await assert.rejects(s.scanner.start(crypto.randomUUID(), 999), /BUSY/);
  await s.scanner.cancel(); release(true); await assert.rejects(first, /CANCELLED/);
  assert.equal(s.opened.length, 0);
});
test('cancel during extraction discards late data and never opens remaining sources', async () => {
  const s = setup([profile(), { ...profile(), id: 'next' }]);
  let release;
  s.api.scripting.executeScript = () => new Promise(resolve => { release = resolve; });
  await s.scanner.start(crypto.randomUUID(), 999); await new Promise(setImmediate);
  assert.ok(release); await s.scanner.cancel();
  release([{ result: { records: [values], observed_at: '2030-06-15T10:00:00Z', origin: 'https://fixture.example' } }]);
  await s.scanner.task;
  assert.equal(s.opened.length, 1); assert.equal(s.scanner.run.captures.length, 0);
  assert.equal(s.session.scan.status, 'CANCELLED');
});
test('timeout, CAPTCHA and permission errors are explicit failures without invented captures', async () => {
  for (const error of ['NOT_READY', 'ACCESS_RESTRICTED', 'PRIVATE_FIELD']) {
    const s = setup(); s.api.scripting.executeScript = async () => [{ result: { error } }];
    await s.scanner.start(crypto.randomUUID(), 999); await s.scanner.task;
    assert.equal(s.scanner.run.status, 'COMPLETED_WITH_ERRORS'); assert.equal(s.scanner.run.captures.length, 0);
    assert.equal(s.scanner.run.sources[0].error, error === 'NOT_READY' ? 'TIMEOUT' : error);
  }
});
test('redirected tabs are not read or closed after the user navigates away', async () => {
  const s = setup();
  const original = s.api.tabs.create;
  s.api.tabs.create = async options => { const tab = await original(options); tab.url = 'https://other.example/account'; return tab; };
  let reads = 0; s.api.scripting.executeScript = async () => { reads++; };
  await s.scanner.start(crypto.randomUUID(), 999); await s.scanner.task;
  assert.equal(reads, 0); assert.deepEqual(s.closed, []); assert.equal(s.scanner.run.sources[0].error, 'SOURCE_CHANGED');
});
test('worker restart preserves completed captures and marks unfinished work interrupted', async () => {
  const s = setup([], { scan: { scan_id: crypto.randomUUID(), status: 'RUNNING', started_at: '2030-06-15T09:00:00Z', finished_at: null, owner_tab: 99, tab: null, captures: [], sources: [{ id: 'fixture', label: 'Fixture', status: 'RUNNING' }] } });
  await s.scanner.ready; assert.equal(s.session.scan.status, 'INTERRUPTED');
  assert.equal(s.session.scan.sources[0].status, 'INTERRUPTED'); assert.equal(s.opened.length, 0);
  assert.equal((await s.scanner.results()).status, 'INTERRUPTED');
});
test('source catalog matches the five user-selected public entry points', () => {
  assert.deepEqual(SOURCES.map(source => source.url), ['https://www.sofascore.com/', 'https://www.betano.pe/', 'https://www.apuestatotal.com/apuestas-deportivas/', 'https://www.teapuesto.pe/sport', 'https://www.flashscore.pe/']);
});
test('session persistence failure cannot leave a phantom running scan or open pages', async () => {
  const s = setup(); s.api.storage.session.set = async () => { throw new Error('STORAGE_UNAVAILABLE'); };
  await assert.rejects(s.scanner.start(crypto.randomUUID(), 999), /STATE_UNAVAILABLE/);
  assert.equal(s.opened.length, 0); assert.equal(s.scanner.run.status, 'INTERRUPTED');
  assert.equal(s.scanner.run.sources[0].status, 'INTERRUPTED');
});
test('included connector failures yield a downloadable diagnostic and do not prevent the next source', async () => {
  const s = setup([nativeProfile('sofascore'), profile()]);
  let requests = 0;
  s.scanner.fetcher = async () => { requests++; return new Response('PRIVATE RESPONSE', { status: 403 }); };
  await s.scanner.start(crypto.randomUUID(), 99); await s.scanner.task;
  const report = await s.scanner.report();
  assert.equal(report.status, 'COMPLETED_WITH_ERRORS'); assert.equal(report.sources[0].error, 'HTTP_403');
  assert.equal(report.sources[1].status, 'COMPLETED'); assert.equal(requests, 1);
  assert.equal(report.count, 1); assert.equal(JSON.stringify(report).includes('PRIVATE RESPONSE'), false);
  assert.equal((await s.scanner.status()).run.preview[0].record.market, 'TOTAL_GOALS');
  assert.deepEqual(s.closed, [1, 2]);
});
test('native HTTP captures retain v3 identity, complete before closing tabs and cancel network work', async () => {
  const s = setup([nativeProfile('sofascore')]);
  const create = s.api.tabs.create;
  s.api.tabs.create = async options => { const tab = await create(options); tab.url = 'https://www.sofascore.com/es/'; return tab; };
  const event = { id: 1, startTimestamp: Date.parse('2030-06-15T20:00:00Z') / 1000, status: { type: 'notstarted' }, tournament: { id: 2, name: 'Fixture League' }, homeTeam: { id: 3, name: 'Fixture Home' }, awayTeam: { id: 4, name: 'Fixture Away' } };
  s.scanner.fetcher = async url => new Response(JSON.stringify({ events: url.endsWith('2030-06-15') ? [event] : [] }));
  await s.scanner.start(crypto.randomUUID(), 99); await s.scanner.task;
  assert.equal((await s.scanner.results()).captures[0].capture_method, 'AUTOMATIC_SOURCE');
  assert.deepEqual(s.closed, [1]);
  const cancelled = setup([nativeProfile('sofascore')]); let signal;
  cancelled.scanner.fetcher = (_url, options) => new Promise((_resolve, reject) => { signal = options.signal; signal.addEventListener('abort', () => reject(new Error('Abort'))); });
  await cancelled.scanner.start(crypto.randomUUID(), 99); await new Promise(setImmediate);
  await cancelled.scanner.cancel(); await cancelled.scanner.task;
  assert.equal(signal.aborted, true); assert.equal((await cancelled.scanner.results()).captures.length, 0);
});
test('closing scan tabs never cancels a user navigation that is still pending', async () => {
  const s = setup();
  const tab = await s.api.tabs.create({ url: 'https://fixture.example/markets', active: false });
  tab.pendingUrl = 'https://other.example/';
  await s.scanner.closeTab({ id: tab.id, url: tab.url }); assert.deepEqual(s.closed, []);
});
