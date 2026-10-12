import { Scanner } from './scanner.mjs';
import { projectPage, UUID } from './scan-contract.mjs';
import { SOURCES } from './sources.mjs';

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
const scanner = new Scanner(chrome);
let settingsTab = null;
let openingSources = false;
let openedAt = 0;
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  const settings = sender.id === chrome.runtime.id && sender.url === chrome.runtime.getURL('scan.html');
  const site = sender.id === chrome.runtime.id && sender.frameId === 0 && projectPage(sender.url) && Number.isInteger(sender.tab?.id);
  if ((!settings && !site) || !message || message.channel !== 'sports_scan_v1' || !UUID.test(message.request_id)) return false;
  const commands = site ? ['STATUS', 'START', 'CANCEL', 'RESULTS', 'REPORT', 'CONFIGURE', 'OPEN_SOURCES'] : ['STATUS', 'GET_CONFIG', 'SET_CONFIG', 'CANCEL'];
  const keys = message.command === 'SET_CONFIG' ? ['channel', 'request_id', 'command', 'config'] : ['channel', 'request_id', 'command'];
  if (!commands.includes(message.command) || Object.keys(message).length !== keys.length || !keys.every(key => Object.hasOwn(message, key))) return false;
  (async () => {
    switch (message.command) {
      case 'GET_CONFIG': return scanner.config();
      case 'SET_CONFIG': await scanner.save(message.config); return scanner.status();
      case 'START': await scanner.start(message.request_id, sender.tab.id); return scanner.status();
      case 'CANCEL': await scanner.cancel(); return scanner.status();
      case 'RESULTS': return scanner.results();
      case 'REPORT': return scanner.report();
      case 'OPEN_SOURCES': {
        if (openingSources || scanner.starting || scanner.run?.status === 'RUNNING') throw new Error('BUSY');
        if (Date.now() - openedAt < 60000) throw new Error('COOLDOWN');
        openingSources = true; openedAt = Date.now();
        try {
          for (const source of SOURCES) await chrome.tabs.create({ url: source.url, active: false });
          return { opened: SOURCES.length };
        } finally { openingSources = false; }
      }
      case 'CONFIGURE': {
        if (settingsTab !== null) {
          try {
            const current = await chrome.tabs.get(settingsTab);
            if (current.url === chrome.runtime.getURL('scan.html')) { await chrome.tabs.update(settingsTab, { active: true }); return {}; }
          } catch { /* Settings tab was closed. */ }
        }
        settingsTab = (await chrome.tabs.create({ url: chrome.runtime.getURL('scan.html') })).id;
        return {};
      }
      default: return scanner.status();
    }
  })().then(data => reply({ ok: true, data })).catch(error => {
    const safe = ['BUSY', 'COOLDOWN', 'NEEDS_CONFIG', 'NEEDS_PERMISSIONS', 'NOT_FINISHED', 'CANCELLED'];
    reply({ ok: false, error: safe.includes(error.message) ? error.message : 'INVALID_REQUEST' });
  });
  return true;
});
chrome.tabs.onRemoved.addListener(tabId => {
  scanner.ready.then(() => { if (scanner.run?.owner_tab === tabId) return scanner.cancel(); }).catch(() => {});
});
