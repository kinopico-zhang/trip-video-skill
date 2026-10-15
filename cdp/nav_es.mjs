// Navigate a tab to Earth Studio (post-reboot recovery), fix window size,
// wait for load, report state.  usage: node nav_es.mjs [url]
const CDP_HTTP = 'http://localhost:9222';
const URL = process.argv[2] || 'https://earth.google.com/studio/';
const list = await (await fetch(CDP_HTTP + '/json/list')).json();
let t = list.find(p => p.url.includes('earth.google.com/studio'));
let navigated = false;
if (!t) {
  t = list.find(p => p.type === 'page' && !p.url.startsWith('devtools'));
  navigated = true;
}
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
let id = 0; const pending = new Map();
function send(method, params = {}) {
  return new Promise((res, rej) => {
    const i = ++id; pending.set(i, { res, rej });
    ws.send(JSON.stringify({ id: i, method, params }));
    setTimeout(() => { if (pending.has(i)) { pending.delete(i); rej(new Error('timeout ' + method)); } }, 30000);
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
await send('Page.enable');
await send('Runtime.enable');
await send('Page.bringToFront');

// window 1920x1080 (viewport resets to 985px after restarts; click coords
// and dialog layout assume full size)
try {
  const { windowId } = await send('Browser.getWindowForTarget');
  await send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'normal', width: 1920, height: 1080 } });
  console.log('window bounds set 1920x1080');
} catch (e) { console.log('setWindowBounds failed (ok in headless):', e.message); }

if (navigated || !t.url.includes('studio') || process.argv.includes('--reload')) {
  await send('Page.navigate', { url: URL });
  console.log('navigated to', URL);
} else {
  console.log('studio tab already open:', t.url);
}
await sleep(15000);
const st = await send('Runtime.evaluate', { expression: `(function(){
  var vp = {w: window.innerWidth, h: window.innerHeight};
  var tc = document.querySelector('.control.timecode');
  var loggedIn = !!document.cookie.match(/SID/) || !!localStorage.getItem('studio:project');
  return JSON.stringify({url: location.href, title: document.title.slice(0,60), vp: vp,
    timecode: tc ? tc.textContent.trim() : null,
    body: document.body.innerText.replace(/\\n+/g, '|').slice(0, 300)});
})()`, returnByValue: true, awaitPromise: true });
console.log('STATE:', st.result.value);
process.exit(0);
