// quick ES live-project state: timecode, duration, kf count, body snippet
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
  var tc = document.querySelector('.control.timecode');
  var proj = null;
  try { proj = JSON.parse(localStorage.getItem('studio:project') || 'null'); } catch (e) {}
  var dur = null, nattr = null;
  if (proj && proj.scene) {
    dur = proj.scene.duration; nattr = proj.scene.attributes ? Object.keys(proj.scene.attributes) : null;
  }
  return JSON.stringify({timecode: tc ? tc.textContent.trim() : null, dur: dur, attrs: nattr,
    body: document.body.innerText.replace(/\\n+/g, '|').slice(0, 200)});
})()`, returnByValue: true, awaitPromise: true });
console.log(r.result.value);
process.exit(0);
