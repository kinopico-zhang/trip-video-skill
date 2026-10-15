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
await send('Runtime.enable');
const r = await send('Runtime.evaluate', { expression: `(function(){
  var out = [];
  document.querySelectorAll('button, [role=button]').forEach(function(e){
    var b = e.getBoundingClientRect();
    if (b.width > 0 && b.height > 0) out.push({t: e.textContent.replace(/\\s+/g,' ').trim().slice(0,24), x: Math.round(b.x+b.width/2), y: Math.round(b.y+b.height/2), w: Math.round(b.width), h: Math.round(b.height)});
  });
  return JSON.stringify(out);
})()`, returnByValue: true });
console.log(r.result.value);
process.exit(0);
