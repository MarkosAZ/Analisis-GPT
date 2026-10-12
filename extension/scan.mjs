import { MAX_CONFIG_BYTES, originsFor, validateConfig } from './scan-contract.mjs';
import { SOURCES } from './sources.mjs';
import { CONNECTORS, nativeProfile } from './connectors.mjs';
const $ = id => document.getElementById(id);
for (const source of SOURCES) {
  const item = document.createElement('li'); const link = document.createElement('a');
  link.href = source.url; link.textContent = source.label; link.target = '_blank'; link.rel = 'noopener noreferrer';
  item.append(link); $('source-catalog').append(item);
  const label = document.createElement('label'); label.className = 'source-choice';
  const check = document.createElement('input'); check.type = 'checkbox'; check.value = source.id;
  check.checked = Boolean(CONNECTORS[source.id]); check.disabled = !CONNECTORS[source.id];
  const description = document.createElement('span');
  const title = document.createElement('strong'); title.textContent = source.label;
  const detail = document.createElement('small'); detail.textContent = CONNECTORS[source.id]?.detail || 'Conector pendiente · captura manual disponible';
  const hosts = document.createElement('small'); hosts.textContent = (CONNECTORS[source.id]?.hosts || []).map(host => new URL(host).hostname).join(' · ');
  description.append(title, detail, hosts); label.append(check, description); $('preset-sources').append(label);
}
const notice = value => { $('scan-notice').textContent = value; $('preset-notice').textContent = value; };
const send = async (command, extra = {}) => {
  const result = await chrome.runtime.sendMessage({ channel: 'sports_scan_v1', request_id: crypto.randomUUID(), command, ...extra });
  if (!result?.ok) throw new Error(result?.error || 'DISCONNECTED');
  return result.data;
};
let busy = false;
function pending(value) { busy = value; $('save-presets').disabled = value; $('save-sources').disabled = value; $('clear-sources').disabled = value; }
send('GET_CONFIG').then(config => {
  $('profiles').value = JSON.stringify(config, null, 2);
  if (config.sources.some(source => CONNECTORS[source.id])) {
    for (const input of $('preset-sources').querySelectorAll('input:not(:disabled)')) input.checked = config.sources.some(source => source.id === input.value);
  }
  notice('Configura fuentes y concede acceso solo a sus sitios.');
}).catch(() => notice('No se pudo conectar con la extensión. Recárgala e inténtalo de nuevo.'));
async function save(config) {
  const old = await send('GET_CONFIG');
  await send('SET_CONFIG', { config });
  const removed = originsFor(old).filter(origin => !originsFor(config).includes(origin));
  if (removed.length) await chrome.permissions.remove({ origins: removed });
  $('profiles').value = JSON.stringify(config, null, 2);
  notice('Fuentes guardadas. Vuelve a la web y pulsa Iniciar escaneo.');
}
$('save-presets').addEventListener('click', async () => {
  if (busy) return;
  const selected = [...$('preset-sources').querySelectorAll('input:checked:not(:disabled)')].map(input => input.value);
  if (!selected.length) { notice('Selecciona al menos una fuente.'); return; }
  const config = validateConfig({ schema_version: 'browser_scan_config_v1', sources: selected.map(nativeProfile) });
  pending(true);
  try {
    // This call is part of the click gesture, before any asynchronous operation.
    if (!await chrome.permissions.request({ origins: originsFor(config) })) { notice('No se concedió acceso. La configuración anterior se conserva.'); return; }
    await save(config);
  } catch (error) { notice(error.message === 'BUSY' ? 'Espera a que termine el escaneo antes de cambiar las fuentes.' : 'No se pudo guardar. Recarga la extensión y revisa los permisos.'); }
  finally { pending(false); }
});
$('profile-file').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > MAX_CONFIG_BYTES) throw new Error();
    const config = validateConfig(JSON.parse(await file.text()));
    $('profiles').value = JSON.stringify(config, null, 2); $('authorized').checked = false;
    notice('Perfil cargado localmente. Revisa las fuentes antes de conceder acceso.');
  } catch { notice('Perfil rechazado. Usa el contrato de configuración, sin datos privados.'); }
  event.target.value = '';
});
$('save-sources').addEventListener('click', async () => {
  if (busy) return;
  try {
    if (!$('authorized').checked) { notice('Confirma que tienes autorización para consultar estas fuentes.'); return; }
    const config = validateConfig(JSON.parse($('profiles').value));
    pending(true);
    // Request directly inside this gesture; no asynchronous step before the prompt.
    if (!(await chrome.permissions.request({ origins: originsFor(config) }))) { notice('Permiso no concedido. No se ha guardado el nuevo perfil.'); return; }
    await save(config);
  } catch (error) { notice(error.message === 'BUSY' ? 'Hay un escaneo en marcha. Cancélalo o espera antes de cambiar las fuentes.' : 'No se guardó la configuración. Comprueba el formato y los permisos.'); }
  finally { pending(false); }
});
$('clear-sources').addEventListener('click', async () => {
  if (busy) return;
  pending(true);
  try {
    await send('CANCEL');
    const config = await send('GET_CONFIG');
    const empty = { schema_version: 'browser_scan_config_v1', sources: [] };
    await send('SET_CONFIG', { config: empty });
    if (config.sources.length) await chrome.permissions.remove({ origins: originsFor(config) });
    $('profiles').value = JSON.stringify(empty, null, 2); $('authorized').checked = false;
    notice('Fuentes eliminadas y permisos retirados.');
  } catch { notice('No se pudieron quitar todos los permisos. Revísalos en la configuración del navegador.'); }
  finally { pending(false); }
});
