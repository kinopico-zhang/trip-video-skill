// Render-queue helpers.  usage:
//   node siq_dl.mjs dump <jobname>   open queue (Alt+Q), print job rows + icons
//   node siq_dl.mjs get <jobname>    click the file_download icon of my row
//   node siq_dl.mjs close            close the queue modal (Esc)
const CDP_HTTP = 'http://localhost:9222';
const [, , cmd, jobName = ''] = process.argv;
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
async function evalp(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
  return r.result?.value;
}
async function key(k, vk, code, mods = 0) {
  await send('Input.dispatchKeyEvent', { type: 'keyDown', modifiers: mods, key: k, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
  await sleep(80);
  await send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: mods, key: k, code, windowsVirtualKeyCode: vk });
}
async function click(x, y) {
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x - 30, y: y - 25 });
  await sleep(60);
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  await sleep(50);
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
}
await send('Runtime.enable');
await send('Page.bringToFront');

if (cmd === 'close') {
  await key('Escape', 27, 'Escape');
  await sleep(800);
  console.log('esc sent');
  process.exit(0);
}

// open queue if not already open
const open0 = await evalp(`!!(document.querySelector('.render-queue-modal') || (document.body.innerText.match(/渲染队列|Render queue|Rendering queue/i) && document.querySelector('.material-icons')))`);
if (!open0) {
  await key('Alt', 18, 'AltLeft', 1); await key('q', 81, 'KeyQ', 1);
  await sleep(2500);
}

if (cmd === 'dump') {
  const rows = await evalp(`(function(){
    var name = ${JSON.stringify(jobName)};
    var out = [];
    // candidate leaf-ish nodes carrying the job name
    var nodes = Array.from(document.querySelectorAll('*')).filter(function(e){
      return e.children.length === 0 && e.textContent && e.textContent.trim() === name;
    });
    nodes.forEach(function(n){
      var row = n;
      for (var k = 0; k < 8 && row.parentElement; k++) {
        row = row.parentElement;
        if (row.getBoundingClientRect().height > 28) break;
      }
      var r = row.getBoundingClientRect();
      var icons = Array.from(row.querySelectorAll('.material-icons, svg, img, [class*=icon]')).filter(function(e){
        var b = e.getBoundingClientRect(); return b.width > 0 && b.width < 60 && b.height > 0 && b.height < 60;
      }).map(function(e){
        var b = e.getBoundingClientRect();
        return {txt: (e.textContent || e.className.baseVal || e.className || '').toString().trim().slice(0, 24),
                x: Math.round(b.x + b.width/2), y: Math.round(b.y + b.height/2)};
      });
      out.push({rowY: Math.round(r.y), rowH: Math.round(r.height), text: row.textContent.replace(/\\s+/g,' ').trim().slice(0, 160), icons: icons});
    });
    return JSON.stringify({modalOpen: !!document.querySelector('.render-queue-modal'), rows: out.slice(0, 4)});
  })()`);
  console.log(rows);
  process.exit(0);
}

if (cmd === 'get') {
  const hit = await evalp(`(function(){
    var name = ${JSON.stringify(jobName)};
    var nodes = Array.from(document.querySelectorAll('*')).filter(function(e){
      return e.children.length === 0 && e.textContent && e.textContent.trim() === name;
    });
    if (!nodes.length) return 'ROWNOTFOUND';
    var row = nodes[0];
    for (var k = 0; k < 8 && row.parentElement; k++) {
      row = row.parentElement;
      if (row.getBoundingClientRect().height > 28) break;
    }
    var icons = Array.from(row.querySelectorAll('.material-icons, svg, img, [class*=icon]')).filter(function(e){
      var b = e.getBoundingClientRect();
      if (!(b.width > 0 && b.width < 60 && b.height > 0 && b.height < 60)) return false;
      var s = ((e.textContent || '') + ' ' + (e.className.baseVal || e.className || '')).toString().toLowerCase();
      return /download|get_app|file_download/.test(s);
    });
    if (!icons.length) return 'NOICON: ' + row.textContent.replace(/\\s+/g,' ').slice(0,120);
    var b = icons[0].getBoundingClientRect();
    return JSON.stringify({x: Math.round(b.x + b.width/2), y: Math.round(b.y + b.height/2)});
  })()`);
  console.log('hit:', hit);
  if (hit.startsWith('{')) {
    const c = JSON.parse(hit);
    await click(c.x, c.y);
    await sleep(1500);
    console.log('clicked download icon at', c.x, c.y);
  }
  process.exit(0);
}
console.log('unknown cmd');
process.exit(1);
