// Open render dialog via 渲染 button click, fill name, verify server radio,
// click Submit.  usage: node render_submit.mjs "<job name>"
const NAME = process.argv[2];
if (!NAME) { console.error('usage: node render_submit.mjs "<job name>"'); process.exit(1); }
const list = await (await fetch('http://localhost:9222/json/list')).json();
const t = list.find(p => (p.url + ' ' + p.title).includes('studio'));
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
let id = 0; const pending = new Map();
function send(method, params = {}) {
  return new Promise((res, rej) => { const i = ++id; pending.set(i, {res, rej});
    ws.send(JSON.stringify({id: i, method, params}));
    setTimeout(() => { if (pending.has(i)) { pending.delete(i); rej(new Error('timeout ' + method)); } }, 15000); });
}
ws.addEventListener('message', ev => { const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); } });
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function evalp(expr) {
  const r = await send('Runtime.evaluate', {expression: expr, returnByValue: true, awaitPromise: true});
  if (r.exceptionDetails) throw new Error('EXC ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result?.value;
}
async function click(x, y) {
  await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: x - 40, y: y - 30});
  await sleep(80);
  await send('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', clickCount: 1});
  await sleep(60);
  await send('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', clickCount: 1});
}
await send('Runtime.enable'); await send('Page.enable');
await send('Page.bringToFront'); await sleep(600);
// 1. open render dialog via DOM click on 渲染 button (synthetic mouse events unreliable)
await evalp('(function(){var r=Array.from(document.querySelectorAll("button")).find(function(e){return e.offsetParent&&e.textContent.trim()==="渲染"});if(!r)return "no-btn";r.click();return "clicked"})()');
await sleep(3000);
const d = JSON.parse(await evalp('(function(){var rs=Array.from(document.querySelectorAll("input[type=radio]")).map(function(e){return e.value+"="+e.checked});var ti=Array.from(document.querySelectorAll("input")).find(function(e){return e.offsetParent&&e.type==="text"});return JSON.stringify({radios:rs,name:ti?ti.value:null})})()'));
if (!d.radios.length) { console.error('render dialog did not open:', JSON.stringify(d)); process.exit(1); }
console.log('dialog ok, name was:', d.name);
// 2. set job name
console.log('name:', await evalp('(function(){var el=Array.from(document.querySelectorAll("input")).find(function(e){return e.offsetParent&&e.type==="text"});if(!el)return "NO-INPUT";var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;s.call(el,' + JSON.stringify(NAME) + ');el.dispatchEvent(new Event("input",{bubbles:true}));el.dispatchEvent(new Event("change",{bubbles:true}));return el.value})()'));
await sleep(400);
// 3. verify server radio
const rs = await evalp('JSON.stringify(Array.from(document.querySelectorAll("input[type=radio]")).map(function(e){return e.value+"="+e.checked}))');
console.log('radios:', rs);
if (rs.indexOf('server=true') < 0) { console.error('server radio not checked'); process.exit(1); }
// 4. click Submit
const c = JSON.parse(await evalp('(function(){var b=Array.from(document.querySelectorAll("button")).find(function(e){return e.offsetParent&&/Submit/i.test(e.textContent)});if(!b)return "null";var r=b.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)})})()'));
console.log('submit at', c.x, c.y);
await evalp('(function(){var b=Array.from(document.querySelectorAll("button")).find(function(e){return e.offsetParent&&/Submit/i.test(e.textContent)});if(!b)return "no-btn";b.click();return "clicked"})()');
await sleep(4000);
// 5. report queue
const q = await evalp('fetch("/studio/api/renders/").then(r=>r.text()).then(t=>t.replace(/^\\)\\]\\}\x27\\n/,""))');
let jobs = []; try { jobs = JSON.parse(q); if (!Array.isArray(jobs) && jobs.renders) jobs = jobs.renders; } catch (e) { console.log('parse fail:', q.slice(0, 120)); }
console.log('mine:', jobs.filter(j => j.name === NAME).map(j => j.id + ':' + j.status).join(' ') || 'NONE');
process.exit(0);
