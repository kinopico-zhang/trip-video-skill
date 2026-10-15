// Poll the ES render API for my job until delivered.
// usage: node siq_poll.mjs <jobname> [timeout_min]
const NAME = process.argv[2] || 'Siquijor Island Map';
const TIMEOUT_MIN = +(process.argv[3] || 15);
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
    setTimeout(() => { if (pending.has(i)) { pending.delete(i); rej(new Error('timeout')); } }, 30000);
  });
}
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id); pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
  }
});
async function poll() {
  const r = await send('Runtime.evaluate', {
    expression: `fetch('/studio/api/renders/').then(r => r.text()).then(t => t.replace(/^\\)\\]\\}'\\n/, ''))`,
    returnByValue: true, awaitPromise: true
  });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 200));
  return r.result.value;
}
const deadline = Date.now() + TIMEOUT_MIN * 60000;
let last = '';
while (Date.now() < deadline) {
  try {
    const raw = await poll();
    let jobs = [];
    try { jobs = JSON.parse(raw); if (!Array.isArray(jobs) && jobs.renders) jobs = jobs.renders; } catch (e) {}
    const mine = jobs.filter(j => j.name === NAME);
    const s = mine.map(j => `${j.id}:${j.status}:${j.progress ?? 0}`).join(' ');
    if (s !== last) { console.log(new Date().toISOString().slice(11, 19), s || '(no jobs yet)'); last = s; }
    const done = mine.find(j => j.status === 'delivered');
    if (done) { console.log('DELIVERED', done.id); process.exit(0); }
    const bad = mine.find(j => /fail|error|cancel/i.test(j.status || ''));
    if (bad) { console.log('FAILED', JSON.stringify(bad).slice(0, 300)); process.exit(1); }
  } catch (e) { console.log('poll err', String(e).slice(0, 120)); }
  await new Promise(r => setTimeout(r, 10000));
}
console.log('TIMEOUT');
process.exit(2);
