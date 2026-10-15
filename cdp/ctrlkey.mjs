#!/usr/bin/env node
// Send a real Ctrl+<key> combo to the CDP tab
// Usage: node ctrlkey.mjs <key>   e.g. node ctrlkey.mjs s
const CDP_HTTP = 'http://localhost:9222';
const match = process.env.CDP_TAB;
const list = await (await fetch(CDP_HTTP + '/json/list')).json();
const t = (match ? list.find(p => (p.url + ' ' + p.title).includes(match)) : null) || list.find(p => p.type === 'page');
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
let id = 0;
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id;
  ws.addEventListener('message', function h(ev) {
    const m = JSON.parse(ev.data);
    if (m.id === i) { ws.removeEventListener('message', h); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
  });
  ws.send(JSON.stringify({ id: i, method, params }));
});
const key = process.argv[2];
const vk = key.toUpperCase().charCodeAt(0);
const code = 'Key' + key.toUpperCase();
await send('Input.dispatchKeyEvent', { type: 'keyDown', modifiers: 2, key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17 });
await send('Input.dispatchKeyEvent', { type: 'keyDown', modifiers: 2, key, code, windowsVirtualKeyCode: vk });
await new Promise(r => setTimeout(r, 120));
await send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: 2, key, code, windowsVirtualKeyCode: vk });
await send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: 0, key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17 });
console.log('ctrl+' + key, 'sent to', t.url.slice(0, 60));
process.exit(0);
