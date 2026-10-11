// Serialized by chrome.scripting into an isolated world. No imports or page scripts.
export function readPublicRows(profile) {
  const deny = /account|wallet|cashier|deposit|withdraw|betslip|bet-slip|my-bets|mis-apuestas|balance|saldo|cuenta|boleta|bilhete|cupom|stake|password|token|secret|session|login/i;
  function visible(node) {
    if (!(node instanceof HTMLElement) || !node.getClientRects().length) return false;
    for (let parent = node; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      if (parent.hidden || parent.getAttribute('aria-hidden') === 'true' || style.display === 'none' || style.visibility !== 'visible' || style.opacity === '0') return false;
    }
    return true;
  }
  function publicNode(node) {
    if (!visible(node) || node === document.body || node === document.documentElement) return false;
    for (let parent = node; parent; parent = parent.parentElement) {
      if (deny.test(`${parent.id} ${parent.className} ${parent.getAttribute('aria-label') || ''}`) ||
          parent.matches('input,textarea,select,form,[contenteditable]:not([contenteditable="false"]),script,style')) return false;
    }
    return true;
  }
  try {
    if (location.href !== profile.url || location.protocol !== 'https:' || deny.test(decodeURIComponent(location.pathname))) return { error: 'SOURCE_CHANGED' };
    if (/captcha|access denied|just a moment|verifica.*humano|iniciar sesi[oó]n/i.test(document.title) ||
        [...document.querySelectorAll('iframe[src*="captcha"],iframe[src*="challenge"],input[type="password"],.cf-challenge')].some(visible)) return { error: 'ACCESS_RESTRICTED' };
    const matches = document.querySelectorAll(profile.row_selector);
    if (matches.length > 50) return { error: 'ROW_LIMIT' };
    const rows = [...matches].filter(visible);
    if (!rows.length) return { error: 'NOT_READY' };
    const records = [];
    for (const row of rows) {
      if (!publicNode(row)) return { error: 'PRIVATE_FIELD' };
      const values = {};
      for (const [key, field] of Object.entries(profile.fields)) {
        if (Object.hasOwn(field, 'value')) { values[key] = field.value; continue; }
        const nodes = field.selector === ':scope' ? [row] : [...row.querySelectorAll(field.selector)];
        if (!nodes.length) return { error: 'NOT_READY' };
        if (nodes.length !== 1) return { error: 'AMBIGUOUS_FIELD' };
        const node = nodes[0];
        if (!publicNode(node)) return { error: 'PRIVATE_FIELD' };
        if (field.attribute === null && (node.querySelector('input,textarea,form,script,style,[hidden],[aria-hidden="true"]') ||
            [...node.querySelectorAll('[id],[class],[aria-label]')].some(child => deny.test(`${child.id} ${child.className} ${child.getAttribute('aria-label') || ''}`)))) return { error: 'PRIVATE_FIELD' };
        const value = (field.attribute === null ? node.innerText : node.getAttribute(field.attribute))?.trim();
        if (!value || value.length > 100 || /[<>@\x00-\x1f\x7f]|:\/\/|bearer\s|gh[pousr]_/i.test(value)) return { error: 'INVALID_FIELD' };
        values[key] = value;
      }
      records.push(values);
    }
    return { records, observed_at: new Date().toISOString(), origin: location.origin };
  } catch { return { error: 'INVALID_SELECTOR' }; }
}
