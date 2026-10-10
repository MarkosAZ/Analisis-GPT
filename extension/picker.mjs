// Self-contained: Chrome serializes this function into the isolated execution world.
export function pickPublicText() {
  return new Promise((resolve) => {
    const blocked = /account|wallet|cashier|deposit|withdraw|betslip|bet-slip|my-bets|mis-apuestas|balance|saldo|cuenta|boleta|bilhete|cupom|stake|password|token|secret|session|login/i;
    if (location.protocol !== 'https:' || blocked.test(decodeURIComponent(location.pathname))) {
      resolve({ error: 'PRIVATE_PAGE' });
      return;
    }
    if (document.querySelector('[data-sports-picker]')) {
      resolve({ error: 'PICKER_ACTIVE' });
      return;
    }
    const host = document.createElement('div');
    host.dataset.sportsPicker = 'true';
    host.style.cssText = 'position:fixed;inset:0;z-index:2147483647;cursor:crosshair;';
    const shadow = host.attachShadow({ mode: 'closed' });
    const notice = document.createElement('div');
    notice.textContent = 'Selecciona un dato público · Esc para cancelar';
    notice.style.cssText = 'position:absolute;top:12px;left:12px;padding:12px 16px;background:#122434;color:#fff;font:14px system-ui;border-radius:8px;pointer-events:none;';
    shadow.append(notice);
    document.documentElement.append(host);
    let timer;
    function finish(result) {
      clearTimeout(timer);
      window.removeEventListener('keydown', onKey, true);
      host.remove();
      resolve(result);
    }
    function onKey(event) {
      if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); finish({ error: 'CANCELLED' }); }
    }
    window.addEventListener('keydown', onKey, true);
    for (const name of ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'touchstart', 'touchend']) {
      host.addEventListener(name, event => { event.preventDefault(); event.stopImmediatePropagation(); }, { passive: false });
    }
    host.addEventListener('click', event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!event.isTrusted) return;
      host.style.pointerEvents = 'none';
      const node = document.elementFromPoint(event.clientX, event.clientY);
      host.style.pointerEvents = 'auto';
      if (!(node instanceof HTMLElement) || node === document.body || node === document.documentElement) {
        finish({ error: 'SELECT_SMALL_FIELD' }); return;
      }
      for (let parent = node; parent; parent = parent.parentElement) {
        const labels = `${parent.id} ${parent.className} ${parent.getAttribute('aria-label') || ''}`;
        if (blocked.test(labels) || parent.matches('input,textarea,select,form,[contenteditable]:not([contenteditable="false"]),[hidden],[aria-hidden="true"]')) {
          finish({ error: 'PRIVATE_FIELD' }); return;
        }
      }
      if (node.querySelector('input,textarea,form,[hidden],[aria-hidden="true"],script,style') ||
          [...node.querySelectorAll('[id],[class],[aria-label]')].some(child => blocked.test(`${child.id} ${child.className} ${child.getAttribute('aria-label') || ''}`))) {
        finish({ error: 'SELECT_SMALL_FIELD' }); return;
      }
      const value = node.innerText.trim();
      if (!value || value.length > 100 || /[<>@\x00-\x1f\x7f]|:\/\/|bearer\s|gh[pousr]_/i.test(value)) {
        finish({ error: 'SELECT_SMALL_FIELD' }); return;
      }
      finish({ text: value, origin: location.origin });
    }, true);
    timer = setTimeout(() => finish({ error: 'TIMEOUT' }), 30000);
  });
}
