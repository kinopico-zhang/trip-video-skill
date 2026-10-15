// scrub N frames forward with ArrowRight, then read the camera attrs panel
const CDP_HTTP = 'http://localhost:9222';
const N = parseInt(process.argv[2] || '27', 10);
const list = await (await fetch(CDP_HTTP + '/json/list')).json();
const t = list.find(p => (p.url + ' ' + p.title).includes('studio')) || list.find(p => p.type === 'page');
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
let id = 0; const pending = new Map();
function send(method, params = {}) {
  return new Promise((res, rej) => {
    const i = ++id; pending.set(i, { res, rej });
    ws.send(JSON.stringify({ id: i, method, params }));
    setTimeout(() => { if (pending.has(i)) { pending.delete(i); rej(new Error('timeout ' + method)); } }, 15000);
  });
}
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id); pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
  }
});
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function evalp(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) return 'EXC: ' + JSON.stringify(r.exceptionDetails).slice(0, 200);
  return r.result?.value;
}
await send('Runtime.enable');
await send('Page.bringToFront');
await sleep(300);
// click the viewport first so the timeline has focus
for (let k = 0; k < N; k++) {
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39, nativeVirtualKeyCode: 39 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39, nativeVirtualKeyCode: 39 });
  await sleep(35);
}
await sleep(700);
const st = await evalp(`(function(){
  var tc = document.querySelector('.control.timecode');
  var m = document.body.innerText.match(/经度\\s*([^\\n|]{1,20})/g);
  var alt = document.body.innerText.match(/海拔高度\\s*([^\\n|]{1,20})/g);
  return JSON.stringify({timecode: tc ? tc.textContent.trim() : null, lonlat: m, alt: alt});
})()`);
console.log(st);
process.exit(0);
