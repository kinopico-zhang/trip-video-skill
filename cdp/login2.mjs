#!/usr/bin/env node
// v2: human-like input + RPC response body capture + console error capture
// usage: node login2.mjs <password>   (credential comes from argv, never
// hardcoded -- keep secrets out of this repo)
import fs from 'fs';
const CDP_HTTP = 'http://localhost:9222';

async function findTab() {
  const l = await (await fetch(CDP_HTTP + '/json/list')).json();
  return l.find(t => t.type === 'page' && (t.url + t.title).includes('accounts')) || l.find(t => t.type === 'page');
}
const tab = await findTab();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });

let id = 0; const pending = new Map();
const reqs = {};           // requestId -> {url, status, done, err}
const bodies = [];         // batchexecute response bodies
const consoleLog = [];
function send(method, params = {}) {
  return new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
}
ws.addEventListener('message', async ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  const p = m.params || {};
  if (m.method === 'Network.requestWillBeSent') reqs[p.requestId] = { url: p.request.url, method: p.request.method, status: 0 };
  else if (m.method === 'Network.responseReceived') { if (reqs[p.requestId]) reqs[p.requestId].status = p.response.status; }
  else if (m.method === 'Network.loadingFinished') {
    const r = reqs[p.requestId]; if (r) { r.done = true;
      if (r.url.includes('batchexecute')) {
        try { const b = await send('Network.getResponseBody', { requestId: p.requestId });
          bodies.push({ url: r.url.slice(0, 90), rpcids: (r.url.match(/rpcids=([^&]*)/) || [])[1], body: (b.body || '').slice(0, 900) });
        } catch (e) { bodies.push({ url: r.url.slice(0, 90), err: e.message }); }
      }
    }
  }
  else if (m.method === 'Network.loadingFailed') { if (reqs[p.requestId]) reqs[p.requestId].err = p.errorText; }
  else if (m.method === 'Runtime.consoleAPICalled') consoleLog.push('console.' + p.type + ': ' + (p.args || []).map(a => a.value || a.description || '').join(' ').slice(0, 200));
  else if (m.method === 'Runtime.exceptionThrown') consoleLog.push('EXCEPTION: ' + JSON.stringify(p.exceptionDetails).slice(0, 300));
});
async function evalp(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result?.value;
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
const rand = (a, b) => a + Math.random() * (b - a);

async function humanType(text) {
  for (const ch of text) {
    const vk = ch.toUpperCase().charCodeAt(0);
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: ch, text: ch, code: 'Key' + ch.toUpperCase(), windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
    await sleep(rand(30, 80));
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: ch, code: 'Key' + ch.toUpperCase(), windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
    await sleep(rand(60, 180));
  }
}
async function mousePath(x, y) {
  let cx = x + rand(-120, 120), cy = y + rand(-90, 90);
  for (let i = 0; i < 6; i++) {
    cx += (x - cx) * 0.4 + rand(-8, 8); cy += (y - cy) * 0.4 + rand(-8, 8);
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: Math.round(cx), y: Math.round(cy) });
    await sleep(rand(40, 110));
  }
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
}
async function humanClick(sel) {
  const r = await evalp(`(()=>{const el=document.querySelector(${JSON.stringify(sel)}); if(!el) return null; const b=el.getBoundingClientRect(); return {x:Math.round(b.x+b.width/2), y:Math.round(b.y+b.height/2)}})()`);
  if (!r) return 'NO ELEMENT ' + sel;
  await mousePath(r.x, r.y);
  await sleep(rand(100, 250));
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: r.x, y: r.y, button: 'left', clickCount: 1 });
  await sleep(rand(50, 110));
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: r.x, y: r.y, button: 'left', clickCount: 1 });
  return 'clicked @' + r.x + ',' + r.y;
}

await send('Network.enable'); await send('Runtime.enable');
await send('Emulation.setFocusEmulationEnabled', { enabled: true });

const state0 = await evalp(`!!document.querySelector('input[type=password]')`);
console.log('password field present:', state0);
if (!state0) { console.log('NOT ON PWD STEP — aborting'); process.exit(1); }
const PWD = process.argv[2];
if (!PWD) { console.error('usage: node login2.mjs <password>'); process.exit(1); }

// move to field, click it, type like a human
const fld = await evalp(`(()=>{const p=document.querySelector('input[type=password]'); const b=p.getBoundingClientRect(); return {x:Math.round(b.x+b.width/2), y:Math.round(b.y+b.height/2)}})()`);
await mousePath(fld.x, fld.y);
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: fld.x, y: fld.y, button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: fld.x, y: fld.y, button: 'left', clickCount: 1 });
await sleep(300);
await humanType(PWD);
await sleep(rand(300, 600));
console.log('pwd len:', await evalp(`document.querySelector('input[type=password]').value.length`));
console.log('submit:', await humanClick('#passwordNext button'));

console.log('waiting 30s...');
await sleep(30000);
const state = await evalp(`({u:location.href.slice(0,150), title:document.title, text:document.body.innerText.replace(/\\n+/g,' | ').slice(0,500)})`);
console.log('STATE:', JSON.stringify(state));
console.log('--- RPC bodies ---');
for (const b of bodies) console.log('RPC', b.rpcids, '=>', (b.body || b.err || '').replace(/\s+/g, ' ').slice(0, 350));
console.log('--- console ---');
for (const c of consoleLog.slice(-15)) console.log(c);
fs.writeFileSync('netlog2.json', JSON.stringify({ reqs, bodies, consoleLog }, null, 1));
console.log('saved netlog2.json');
process.exit(0);
