import { automaticCapture, MAX_CAPTURES, originsFor, profileHash, TERMINAL, UUID, validateConfig } from './scan-contract.mjs';
import { readPublicRows } from './reader.mjs';
import { isNative, nativeLanding, readConnector } from './connectors.mjs';

const emptyConfig = () => ({ schema_version: 'browser_scan_config_v1', sources: [] });
export class Scanner {
  constructor(api, { now = () => Date.now(), sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), fetcher = fetch } = {}) {
    this.api = api; this.now = now; this.sleep = sleep; this.fetcher = fetcher;
    this.run = null; this.starting = false; this.epoch = 0; this.writes = Promise.resolve();
    this.ready = this.restore();
  }
  async restore() {
    const { scan } = await this.api.storage.session.get('scan');
    this.run = scan || null;
    if (this.run?.status === 'RUNNING') {
      this.run.status = 'INTERRUPTED'; this.run.finished_at = new Date(this.now()).toISOString();
      for (const source of this.run.sources) if (['PENDING', 'RUNNING'].includes(source.status)) source.status = 'INTERRUPTED';
      await this.closeTab(this.run.tab); this.run.tab = null; await this.persist();
    }
  }
  persist() {
    const snapshot = structuredClone(this.run);
    const write = this.writes.then(() => this.api.storage.session.set({ scan: snapshot }));
    this.writes = write.catch(() => {});
    return write;
  }
  async config() {
    const { scanConfig } = await this.api.storage.local.get('scanConfig');
    return validateConfig(scanConfig || emptyConfig());
  }
  async save(config) {
    await this.ready;
    if (this.starting || this.run?.status === 'RUNNING') throw new Error('BUSY');
    validateConfig(config);
    if (!(await this.api.permissions.contains({ origins: originsFor(config) }))) throw new Error('NEEDS_PERMISSIONS');
    await this.api.storage.local.set({ scanConfig: structuredClone(config) });
  }
  async status() {
    await this.ready;
    const config = await this.config();
    return { configured: config.sources.length,
      permitted: !config.sources.length || await this.api.permissions.contains({ origins: originsFor(config) }),
      run: this.run ? { scan_id: this.run.scan_id, status: this.run.status, started_at: this.run.started_at,
        finished_at: this.run.finished_at, count: this.run.captures.length, sources: structuredClone(this.run.sources),
        preview: structuredClone(this.run.captures.slice(0, 20).map(capture => ({ kind: capture.kind, record: capture.record, captured_at: capture.captured_at, source_origin: capture.source_origin }))) } : null };
  }
  async start(requestId, ownerTab) {
    await this.ready;
    if (!UUID.test(requestId) || !Number.isInteger(ownerTab)) throw new Error('INVALID_REQUEST');
    if (this.run?.scan_id === requestId) return;
    if (this.starting || this.run?.status === 'RUNNING') throw new Error('BUSY');
    if (this.run && this.now() - Date.parse(this.run.started_at) < 60000) throw new Error('COOLDOWN');
    this.starting = true;
    const epoch = this.epoch;
    try {
      const config = structuredClone(await this.config());
      if (!config.sources.length) throw new Error('NEEDS_CONFIG');
      if (!(await this.api.permissions.contains({ origins: originsFor(config) }))) throw new Error('NEEDS_PERMISSIONS');
      if (epoch !== this.epoch) throw new Error('CANCELLED');
      const run = { scan_id: requestId, status: 'RUNNING', started_at: new Date(this.now()).toISOString(),
        finished_at: null, owner_tab: ownerTab, tab: null, captures: [],
        sources: config.sources.map(source => ({ id: source.id, label: source.label, reader: source.reader, version: source.version, status: 'PENDING', error: null, count: 0 })) };
      this.run = run;
      this.abort = new AbortController();
      try { await this.persist(); }
      catch { run.status = 'INTERRUPTED'; run.finished_at = new Date(this.now()).toISOString(); for (const source of run.sources) source.status = 'INTERRUPTED'; throw new Error('STATE_UNAVAILABLE'); }
      this.task = this.drive(run, config.sources).catch(async () => {
        if (this.alive(run)) {
          run.status = 'INTERRUPTED'; run.finished_at = new Date(this.now()).toISOString();
          for (const source of run.sources) if (['PENDING', 'RUNNING'].includes(source.status)) source.status = 'INTERRUPTED';
        }
        await this.closeTab(run.tab); run.tab = null;
        await this.persist().catch(() => {});
      });
    } finally { this.starting = false; }
  }
  alive(run) { return this.run === run && run.status === 'RUNNING'; }
  async closeTab(tab) {
    if (!tab) return;
    try {
      const current = await this.api.tabs.get(tab.id);
      if (current.pendingUrl && current.pendingUrl !== tab.url) return;
      if (current.url === tab.url || current.pendingUrl === tab.url) await this.api.tabs.remove(tab.id);
    } catch { /* Do not touch user tabs or tabs already closed. */ }
  }
  async cancel() {
    await this.ready; this.epoch += 1;
    this.abort?.abort();
    const run = this.run;
    if (!run || run.status !== 'RUNNING') return;
    run.status = 'CANCELLED'; run.finished_at = new Date(this.now()).toISOString();
    for (const source of run.sources) if (['PENDING', 'RUNNING'].includes(source.status)) source.status = 'CANCELLED';
    await this.closeTab(run.tab); run.tab = null; await this.persist();
  }
  async results() {
    await this.ready;
    if (!this.run || !TERMINAL.includes(this.run.status)) throw new Error('NOT_FINISHED');
    return { schema_version: 'browser_scan_v1', scan_id: this.run.scan_id, started_at: this.run.started_at,
      finished_at: this.run.finished_at, status: this.run.status, captures: structuredClone(this.run.captures) };
  }
  async report() {
    await this.ready;
    if (!this.run || !TERMINAL.includes(this.run.status)) throw new Error('NOT_FINISHED');
    return { schema_version: 'browser_scan_report_v1', extension_version: this.api.runtime?.getManifest?.().version || null, scan_id: this.run.scan_id, started_at: this.run.started_at,
      finished_at: this.run.finished_at, status: this.run.status, count: this.run.captures.length,
      sources: structuredClone(this.run.sources) };
  }
  async drive(run, profiles) {
    for (let i = 0; i < profiles.length; i += 1) {
      if (!this.alive(run)) return;
      const source = profiles[i]; const item = run.sources[i];
      item.status = 'RUNNING'; await this.persist();
      let owned = null;
      try {
        if (!this.alive(run)) return;
        if (!(await this.api.permissions.contains({ origins: originsFor({ sources: [source] }) }))) throw new Error('NEEDS_PERMISSIONS');
        if (!this.alive(run)) return;
        const tab = await this.api.tabs.create({ url: source.url, active: false });
        owned = { id: tab.id, url: source.url };
        if (!this.alive(run)) return;
        run.tab = owned; await this.persist();
        const deadline = this.now() + 30000;
        let read = null;
        while (this.alive(run) && this.now() < deadline) {
          const current = await this.api.tabs.get(tab.id);
          const waitingForInitialNavigation = current.url === 'about:blank' && current.pendingUrl === source.url;
          const accepted = value => value === owned.url || (!owned.resolved && isNative(source) && nativeLanding(source, value));
          if ((!waitingForInitialNavigation && current.url && !accepted(current.url)) || (current.pendingUrl && !accepted(current.pendingUrl))) throw new Error('SOURCE_CHANGED');
          if (current.status === 'complete') {
            if (isNative(source) && !owned.resolved) { owned.url = current.url; owned.resolved = true; await this.persist(); }
            const results = isNative(source)
              ? [{ result: await readConnector(source, this.api, tab.id, { now: this.now, fetcher: this.fetcher, signal: this.abort.signal }) }]
              : await this.api.scripting.executeScript({ target: { tabId: tab.id, frameIds: [0] }, world: 'ISOLATED', func: readPublicRows, args: [source] });
            if (!this.alive(run)) return;
            read = results[0]?.result;
            if (read && !read.error) break;
            if (read?.error !== 'NOT_READY') throw new Error(read?.error || 'READ_FAILED');
          }
          await this.sleep(500);
        }
        if (!this.alive(run)) return;
        if (this.now() >= deadline) throw new Error('TIMEOUT');
        if (!read || read.error) throw new Error('TIMEOUT');
        const current = await this.api.tabs.get(tab.id);
        if (current.url !== owned.url || current.pendingUrl || read.origin !== new URL(source.url).origin) throw new Error('SOURCE_CHANGED');
        if (!Array.isArray(read.records) || !read.records.length || read.records.length > 50 ||
            !Number.isFinite(Date.parse(read.observed_at)) || Date.parse(read.observed_at) > this.now() ||
            Date.parse(read.observed_at) < Date.parse(run.started_at)) throw new Error('READ_FAILED');
        if (run.captures.length + read.records.length > MAX_CAPTURES) throw new Error('CAPTURE_LIMIT');
        const hash = await profileHash(source);
        const captures = read.records.map(row => automaticCapture(source, row, read.observed_at, run.scan_id, hash));
        if (!this.alive(run)) return;
        run.captures.push(...captures); item.count = captures.length; item.status = 'COMPLETED';
        item.skipped = read.skipped || 0; item.truncated = read.truncated || 0; item.reader = source.reader;
      } catch (error) {
        if (!this.alive(run)) return;
        item.status = 'FAILED';
        const codes = ['NEEDS_PERMISSIONS', 'SOURCE_CHANGED', 'ACCESS_RESTRICTED', 'ROW_LIMIT', 'PRIVATE_FIELD', 'AMBIGUOUS_FIELD', 'INVALID_FIELD', 'INVALID_SELECTOR', 'READ_FAILED', 'TIMEOUT', 'CAPTURE_LIMIT', 'HTTP_401', 'HTTP_403', 'HTTP_429', 'SOURCE_HTTP_ERROR', 'NETWORK_ERROR', 'RESPONSE_LIMIT', 'SCHEMA_CHANGED', 'AMBIGUOUS_SOURCE', 'NO_PUBLIC_DATA'];
        item.error = codes.includes(error.message) ? error.message : 'READ_FAILED';
      } finally {
        await this.closeTab(owned);
        if (run.tab?.id === owned?.id) run.tab = null;
        await this.persist();
      }
      if (!this.alive(run)) return;
      if (i + 1 < profiles.length) await this.sleep(2000);
    }
    if (!this.alive(run)) return;
    run.status = run.sources.some(source => source.status === 'FAILED') ? 'COMPLETED_WITH_ERRORS' : 'COMPLETED';
    run.finished_at = new Date(this.now()).toISOString(); await this.persist();
  }
}
