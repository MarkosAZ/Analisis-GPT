// Only the public event projection leaves the page. No hooks, cookies, request
// headers, whole application state, HTML, login actions, or market button clicks.
export function collectBetano() {
  if (location.origin !== 'https://www.betano.pe' || !['/', '/sport/futbol/'].includes(location.pathname) || location.search || location.hash) return { error: 'SOURCE_CHANGED' };
  const visible = node => node.getClientRects().length && getComputedStyle(node).visibility === 'visible';
  if (/captcha|access denied|just a moment|verifica.*humano/i.test(document.title) ||
      [...document.querySelectorAll('iframe[src*="captcha"],iframe[src*="challenge"],input[type="password"]')].some(visible)) return { error: 'ACCESS_RESTRICTED' };
  const denied = /account|wallet|cashier|deposit|withdraw|betslip|bet.?slip|my.?bets|balance|saldo|cuenta|boleta|stake|password|token|secret|session|login|user|customer|profile/i;
  const text = value => typeof value === 'string' && value.length <= 100 && !/[<>@\x00-\x1f\x7f]|:\/\/|bearer\s|gh[pousr]_/i.test(value) ? value.trim() : null;
  const id = value => /^[A-Za-z0-9_.:-]{1,100}$/.test(String(value ?? '')) ? String(value) : null;
  const roots = [window.initial_state, window.__INITIAL_STATE__, window.__NEXT_DATA__];
  const embedded = document.getElementById('__NEXT_DATA__');
  if (embedded?.textContent.length <= 2 * 1024 * 1024) { try { roots.push(JSON.parse(embedded.textContent)); } catch { /* Unsupported embedded format. */ } }
  const stack = roots.filter(Boolean).map(value => [value, 0]); const seen = new WeakSet();
  const events = []; let inspected = 0;
  while (stack.length && inspected++ < 20000) {
    const [value, depth] = stack.pop();
    if (!value || typeof value !== 'object' || seen.has(value) || depth > 15) continue;
    seen.add(value);
    // Require explicitly identified football; never assign a sport from a homepage default.
    const football = String(value.sportId) === '1' || /^(football|futbol|fútbol)$/i.test(value.sport?.name || value.sportName || '') ||
      (location.pathname === '/sport/futbol/' && value.sportId == null && value.sportName == null && value.sport == null);
    if (football && id(value.id) && Array.isArray(value.markets) && (value.participants?.length === 2 || text(value.name))) {
      if (value.isLive || value.isSuspended) continue;
      const markets = [];
      for (const market of value.markets.slice(0, 100)) {
        if (!market || market.isSuspended || !text(market.name) || !Array.isArray(market.selections) || ![2, 3].includes(market.selections.length)) continue;
        const selections = market.selections.map(selection => ({ name: text(selection?.name), price: selection?.price ?? selection?.odds ?? selection?.decimalOdds,
          disabled: Boolean(selection?.isDisabled || selection?.isSuspended) }));
        if (selections.some(selection => !selection.name || selection.disabled || !/^[0-9]+(?:\.[0-9]{1,4})?$/.test(String(selection.price)) || Number(selection.price) <= 1)) continue;
        const period = market.period ?? market.periodName ?? null;
        if (period !== null && !text(period)) continue;
        markets.push({ name: text(market.name), period, selections: selections.map(({ name, price }) => ({ name, price: String(price) })) });
      }
      const caption = text(value.name)?.split(/\s+-\s+|\s+vs\.?\s+/i);
      events.push({ id: id(value.id), home_name: caption?.length === 2 ? text(caption[0]) : null,
        away_name: caption?.length === 2 ? text(caption[1]) : null, markets });
      if (events.length >= 100) break;
      continue;
    }
    // Bound traversal and do not invoke accessor properties while examining page state.
    for (const key of Object.keys(value).slice(0, 2000)) {
      if (stack.length >= 20000) break;
      if (denied.test(key)) continue;
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (Object.hasOwn(descriptor, 'value') && descriptor.value && typeof descriptor.value === 'object') stack.push([descriptor.value, depth + 1]);
    }
  }
  return { events };
}
