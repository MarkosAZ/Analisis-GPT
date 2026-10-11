// Declaratively injected only into the project's web page, never source sites.
(() => {
  if (window.top !== window) return;
  const own = location.origin === 'https://markosaz.github.io' && ['/Analisis-GPT/', '/Analisis-GPT/index.html'].includes(location.pathname);
  const local = ['http://127.0.0.1:8000', 'http://localhost:8000'].includes(location.origin) && ['/', '/index.html'].includes(location.pathname);
  if ((!own && !local) || location.search) return;
  window.addEventListener('message', async event => {
    const data = event.data;
    if (event.source !== window || event.origin !== location.origin || !data || data.channel !== 'sports_scan_request_v1' ||
        Object.keys(data).sort().join(',') !== 'channel,command,request_id' ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(data.request_id) ||
        !['STATUS', 'START', 'CANCEL', 'RESULTS', 'CONFIGURE', 'OPEN_SOURCES'].includes(data.command)) return;
    let result;
    try { result = await chrome.runtime.sendMessage({ ...data, channel: 'sports_scan_v1' }); }
    catch { result = { ok: false, error: 'DISCONNECTED' }; }
    window.postMessage({ channel: 'sports_scan_response_v1', request_id: data.request_id, result }, location.origin);
  });
})();
