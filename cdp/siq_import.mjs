// Robust ES project import (V5-verified flow from memory):
// bringToFront -> intercept file chooser -> Ctrl+I -> fileChooserOpened ->
// setFileInputFiles on the last input[type=file] -> manual change dispatch.
// usage: node siq_import.mjs 'C:\path\file.esp'
const CDP_HTTP = 'http://localhost:9222';
const FILE = process.argv[2];
if (!FILE) { console.error('usage: node siq_import.mjs <C:\\path\\file.esp>'); process.exit(1); }
const list = await (await fetch(CDP_HTTP + '/json/list')).json();
const t = list.find(p => (p.url + ' ' + p.title).includes('studio')) || list.find(p => p.type === 'page');
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
let id = 0; const pending = new Map();
let chooser = null;
const chooserWait = new Promise(res => { chooser = res; });
function send(method, params = {}) {
  return new Promise((res, rej) => {
    const i = ++id; pending.set(i, { res, rej });
    ws.send(JSON.stringify({ id: i, method, params }));
    setTimeout(() => { if (pending.has(i)) { pending.delete(i); rej(new Error('timeout ' + method)); } }, 20000);
  });
}
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id); pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
  } else if (m.method === 'Page.fileChooserOpened') {
    chooser(m.params);
  }
});
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function evalp(expr, returnByValue = true) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
  return r.result;
}
await send('Page.enable');
await send('DOM.enable');
await send('Runtime.enable');
await send('Page.bringToFront');
await sleep(300);

await send('Page.setInterceptFileChooserDialog', { enabled: true });
// Ctrl+I (import project)
await send('Input.dispatchKeyEvent', { type: 'keyDown', modifiers: 2, key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17 });
await send('Input.dispatchKeyEvent', { type: 'keyDown', modifiers: 2, key: 'i', code: 'KeyI', windowsVirtualKeyCode: 73, nativeVirtualKeyCode: 73 });
await sleep(120);
await send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: 2, key: 'i', code: 'KeyI', windowsVirtualKeyCode: 73 });
await send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: 0, key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17 });

const opened = await Promise.race([chooserWait, sleep(6000).then(() => null)]);
if (!opened) { console.error('file chooser did NOT open (Ctrl+I failed)'); process.exit(1); }
console.log('fileChooserOpened backendNodeId:', opened.backendNodeId);

// objectId of the LAST input[type=file] (no returnByValue!)
const obj = await evalp(`(function(){
  var els = document.querySelectorAll('input[type=file]');
  return els[els.length - 1];
})()`, false);
if (!obj.objectId) { console.error('no objectId for file input'); process.exit(1); }
console.log('input objectId:', obj.objectId);

await send('DOM.setFileInputFiles', { files: [FILE], objectId: obj.objectId });
console.log('files set:', FILE);
await sleep(1200);
// ES may not react to setFileInputFiles alone -> nudge change event
const st = await evalp(`(function(){
  var els = document.querySelectorAll('input[type=file]');
  var el = els[els.length - 1];
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return 'change dispatched, n=' + els.length;
})()`);
console.log(st.value);
await sleep(4000);
const state = await evalp(`(function(){
  var tc = document.querySelector('.control.timecode');
  var proj = null;
  try { proj = JSON.parse(localStorage.getItem('studio:project') || 'null'); } catch (e) {}
  return JSON.stringify({timecode: tc ? tc.textContent.trim() : null,
                         body: document.body.innerText.replace(/\\n+/g, '|').slice(0, 180)});
})()`);
console.log('state:', state.value);
process.exit(0);
