const CDP_HTTP = 'http://localhost:9222';
const list = await (await fetch(CDP_HTTP + '/json/list')).json();
const t = list.find(p => (p.url + ' ' + p.title).includes('studio')) || list.find(p => p.type === 'page');
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
let id = 0; const pending = new Map();
function send(method, params = {}) {
  return new Promise((res, rej) => {
    const i = ++id; pending.set(i, { res, rej });
    ws.send(JSON.stringify({ id: i, method, params }));
    setTimeout(() => { if (pending.has(i)) { pending.delete(i); rej(new Error('timeout')); } }, 15000);
  });
}
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id); pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
  }
});
await send('Runtime.enable');
const r = await send('Runtime.evaluate', { expression: `(function(){
  var info = {ng: typeof ng, ngKeys: (typeof ng !== 'undefined') ? Object.keys(ng) : null};
  try { info.root = typeof getAllAngularRootElements === 'function' ? getAllAngularRootElements().length : 'no fn'; } catch(e) { info.root = 'err'; }
  var wkeys = Object.keys(window).filter(function(k){return /studio|project|scene|render/i.test(k);});
  info.win = wkeys.slice(0, 20);
  return JSON.stringify(info);
})()`, returnByValue: true, awaitPromise: true });
console.log(r.result.value);
process.exit(0);
