// Verify the imported project in ES: timecode + all attribute-panel values.
// usage: node siq_verify.mjs
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
async function evalp(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result?.value;
}
await send('Runtime.enable');

const info = await evalp(`(function(){
  var tc = document.querySelector('.control.timecode');
  var groups = [];
  Array.from(document.querySelectorAll('.attribute-group-header')).forEach(function(h){
    var vals = Array.from(h.parentElement.querySelectorAll('.presentedValue')).map(function(e){return e.textContent.trim();});
    groups.push({header: h.textContent.trim().slice(0,40), values: vals.slice(0,8)});
  });
  var inputs = Array.from(document.querySelectorAll('.presentedValue input, .attribute-value input')).map(function(e){return e.value;}).slice(0,12);
  return JSON.stringify({timecode: tc ? tc.textContent.trim() : null, groups: groups, inputs: inputs});
})()`);
console.log(info);
process.exit(0);
