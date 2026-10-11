import test from 'node:test';
import assert from 'node:assert/strict';
let listener;
const created=[];
const local={};const session={};
const bag=value=>({get:async()=>structuredClone(value),set:async patch=>Object.assign(value,structuredClone(patch)),setAccessLevel:async()=>{}});
globalThis.chrome={
  runtime:{id:'test-extension',getURL:path=>`chrome-extension://test-extension/${path}`,onMessage:{addListener:handler=>{listener=handler;}}},
  sidePanel:{setPanelBehavior:()=>{}},storage:{local:bag(local),session:bag(session)},
  permissions:{contains:async()=>true},
  tabs:{onRemoved:{addListener:()=>{}},create:async options=>{created.push(options);return {id:created.length};},get:async()=>{throw new Error('CLOSED');}},
};
await import('../../extension/background.js');
const site={id:'test-extension',frameId:0,url:'https://markosaz.github.io/Analisis-GPT/',tab:{id:99}};
const message=command=>({channel:'sports_scan_v1',request_id:crypto.randomUUID(),command});
function send(data,sender=site){return new Promise(resolve=>{const accepted=listener(data,sender,resolve);if(!accepted)resolve(null);});}
test('background rejects unauthorized senders, frames and config writes from website',async()=>{
  for(const sender of [{...site,id:'other-extension'},{...site,frameId:1},{...site,url:'https://markosaz.github.io/other/'},{...site,url:'https://www.betano.pe/'}]) assert.equal(await send(message('OPEN_SOURCES'),sender),null);
  assert.equal(await send({...message('START'),url:'https://evil.example'}),null);
  assert.equal(await send({...message('SET_CONFIG'),config:{}},site),null);
  assert.deepEqual(created,[]);
});
test('website opens exactly five fixed public destinations and duplicate opening is throttled',async()=>{
  const result=await send(message('OPEN_SOURCES'));
  assert.equal(result.ok,true);assert.equal(result.data.opened,5);assert.equal(created.length,5);
  assert.equal(created.every(tab=>tab.active===false&&tab.url.startsWith('https://')),true);
  const duplicate=await send(message('OPEN_SOURCES'));assert.equal(duplicate.error,'COOLDOWN');assert.equal(created.length,5);
});
test('only extension settings page can read profiles',async()=>{
  assert.equal(await send(message('GET_CONFIG')),null);
  const result=await send(message('GET_CONFIG'),{id:'test-extension',url:'chrome-extension://test-extension/scan.html'});
  assert.equal(result.ok,true);assert.deepEqual(result.data.sources,[]);
});
