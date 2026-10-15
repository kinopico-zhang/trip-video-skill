// click a visible element by (substring) text.  usage: node click_text.mjs "文本" [--exact]
const CDP_HTTP = 'http://localhost:9222';
const NEEDLE = process.argv[2];
const EXACT = process.argv.includes('--exact');
if (!NEEDLE) { console.error('usage: node click_text.mjs <text>'); process.exit(1); }
const list = await (await fetch(CDP_HTTP + '/json/list')).json();
const t = list.find(p => (p.url + ' ' + p.title).includes('studio')) || list.find(p => p.type === 'page');
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
let id = 0; const pending = new Map();
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
  }
});
const sleep = ms => new Promise(r => setTimeout(r, ms));
await send('Runtime.enable');
await send('Page.bringToFront');
const hit = await send('Runtime.evaluate', { expression: `(function(){
  var needle = ${JSON.stringify(NEEDLE)};
  var els = Array.from(document.querySelectorAll('button, a, [role=button], .menu-item, li, div, span'))
    .filter(function(e){
      if (!e.offsetParent && e.tagName !== 'BODY') return false;
      var txt = (e.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!txt) return false;
      return ${EXACT ? 'txt === needle' : 'txt.indexOf(needle) >= 0 && txt.length < needle.length + 20'};
    });
  if (!els.length) return 'NOTFOUND';
  var el = els[0];
  for (var k = 0; k < 3 && el.parentElement; k++) {
    var p = el.parentElement;
    if (p.tagName === 'BUTTON' || p.getAttribute('role') === 'button' || p.tagName === 'A') el = p;
  }
  var r = el.getBoundingClientRect();
  return JSON.stringify({x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), w: Math.round(r.width), h: Math.round(r.height), txt: el.textContent.replace(/\\s+/g,' ').trim().slice(0,40)});
})()`, returnByValue: true, awaitPromise: true });
const v = hit.result.value;
console.log('hit:', v);
if (!v.startsWith('{')) process.exit(1);
const c = JSON.parse(v);
await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: c.x - 25, y: c.y - 20 });
await sleep(80);
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: c.x, y: c.y, button: 'left', clickCount: 1 });
await sleep(60);
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: c.x, y: c.y, button: 'left', clickCount: 1 });
console.log('clicked', c.txt);
process.exit(0);
