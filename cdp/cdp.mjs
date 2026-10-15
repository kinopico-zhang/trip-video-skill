#!/usr/bin/env node
// Minimal CDP client — drives the Windows Chrome instance via localhost:9222
// Usage: node cdp.mjs <command> [args...]   (set CDP_TAB env to match a tab by url/title substring)
import fs from 'fs';

const CDP_HTTP = 'http://localhost:9222';

async function listPages() {
  const list = await (await fetch(CDP_HTTP + '/json/list')).json();
  return list.filter(t => t.type === 'page');
}

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.handlers = [];
    ws.addEventListener('message', ev => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject, timer } = this.pending.get(msg.id);
        clearTimeout(timer); this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      } else if (msg.method) this.handlers.forEach(h => h(msg));
    });
  }
  static async connect(match) {
    const pages = await listPages();
    if (!pages.length) throw new Error('no page targets');
    let t = match ? pages.find(p => (p.url + ' ' + p.title).includes(match)) : pages[0];
    if (!t) t = pages[0];
    const ws = new WebSocket(t.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
    const c = new CDP(ws); c.targetInfo = t;
    await c.send('Runtime.enable'); await c.send('Page.enable');
    return c;
  }
  send(method, params = {}, timeoutMs = 60000) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('timeout: ' + method)); }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expr, awaitPromise = true) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise });
    if (r.exceptionDetails) throw new Error('JS error: ' + JSON.stringify(r.exceptionDetails).slice(0, 800));
    return r.result?.value;
  }
}

const [, , cmd, ...args] = process.argv;
const match = process.env.CDP_TAB;
try {
  switch (cmd) {
    case 'tabs': {
      for (const p of await listPages()) console.log(p.targetId?.slice(0, 8), '|', p.url, '|', p.title);
      break;
    }
    case 'info': {
      const c = await CDP.connect(match);
      console.log(c.targetInfo.url, '|', c.targetInfo.title);
      break;
    }
    case 'nav': {
      const c = await CDP.connect(match);
      await c.send('Page.navigate', { url: args[0] });
      for (let i = 0; i < 40; i++) {
        await new Promise(r => setTimeout(r, 500));
        const st = await c.eval('document.readyState', false).catch(() => null);
        if (st === 'complete') break;
      }
      console.log('navigated:', await c.eval('location.href', false));
      break;
    }
    case 'eval': {
      const c = await CDP.connect(match);
      console.log(JSON.stringify(await c.eval(args[0])));
      break;
    }
    case 'shot': {
      const c = await CDP.connect(match);
      const r = await c.send('Page.captureScreenshot', { format: 'png' });
      const out = args[0] || 'shot.png';
      fs.writeFileSync(out, Buffer.from(r.data, 'base64'));
      console.log('saved', out);
      break;
    }
    case 'click': {
      const c = await CDP.connect(match);
      console.log(await c.eval(`(() => { const el = document.querySelector(${JSON.stringify(args[0])});
        if (!el) return 'not found: ' + ${JSON.stringify(args[0])};
        el.scrollIntoView({ block: 'center' }); el.click(); return 'clicked'; })()`));
      break;
    }
    case 'mouse': {
      const c = await CDP.connect(match);
      const [x, y, action = 'click'] = args.map((v, i) => (i < 2 ? +v : v));
      const base = { x, y, button: 'left', clickCount: 1 };
      if (action === 'click') {
        await c.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...base });
        await c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...base });
      } else {
        await c.send('Input.dispatchMouseEvent', { type: action === 'down' ? 'mousePressed' : action === 'up' ? 'mouseReleased' : action, ...base });
      }
      console.log('mouse', action, x, y);
      break;
    }
    case 'focus': {
      const c = await CDP.connect(match);
      await c.send('Emulation.setFocusEmulationEnabled', { enabled: args[0] !== 'off' });
      console.log('focus emulation:', args[0] !== 'off' ? 'ON' : 'OFF');
      break;
    }
    case 'window': {
      const c = await CDP.connect(match);
      const { windowId } = await c.send('Browser.getWindowForTarget');
      await c.send('Browser.setWindowBounds', { windowId, bounds: { windowState: args[0] || 'normal' } });
      console.log('window', windowId, '->', args[0] || 'normal');
      break;
    }
    case 'clicktext': {
      // clicktext <exact text> [index] — real mouse click on element containing text
      const c = await CDP.connect(match);
      const txt = args[0];
      const idx = parseInt(args[1] || '0');
      const r = await c.eval(`(()=>{
        const leaves = Array.from(document.querySelectorAll('*')).filter(e=>e.children.length===0 && e.textContent && e.textContent.trim()===${JSON.stringify(txt)});
        if (!leaves.length) return null;
        const el = leaves[Math.min(${idx}, leaves.length-1)];
        let target = el;
        for (let i=0;i<3 && target.parentElement;i++){ target = target.parentElement; }
        const b = target.getBoundingClientRect();
        const eb = el.getBoundingClientRect();
        const rect = (b.width>5 && b.height>5) ? b : eb;
        return {x: Math.round(rect.x+rect.width/2), y: Math.round(rect.y+rect.height/2), w: Math.round(rect.width), h: Math.round(rect.height), found: leaves.length};
      })()`, false);
      if (!r) { console.log('NOT FOUND: ' + txt); break; }
      await c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: r.x - 60, y: r.y - 40 });
      await new Promise(res => setTimeout(res, 80));
      await c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: r.x, y: r.y });
      await new Promise(res => setTimeout(res, 60));
      await c.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: r.x, y: r.y, button: 'left', clickCount: 1 });
      await new Promise(res => setTimeout(res, 50));
      await c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: r.x, y: r.y, button: 'left', clickCount: 1 });
      console.log(`clicked "${txt}" at ${r.x},${r.y} (${r.found} matches)`);
      break;
    }
    case 'front': {
      const c = await CDP.connect(match);
      await c.send('Page.bringToFront');
      console.log('brought to front');
      break;
    }
    case 'insert': {
      const c = await CDP.connect(match);
      await c.send('Input.insertText', { text: args[0] });
      console.log('inserted', args[0].length, 'chars');
      break;
    }
    case 'key': {
      const c = await CDP.connect(match);
      const key = args[0];
      const defs = {
        Enter: { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' },
        Tab: { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 },
        Escape: { key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 },
        Backspace: { key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 },
      };
      const k = defs[key] || { key, code: 'Key' + key.toUpperCase(), windowsVirtualKeyCode: key.length === 1 ? key.toUpperCase().charCodeAt(0) : undefined, text: key.length === 1 ? key : undefined };
      await c.send('Input.dispatchKeyEvent', { type: 'keyDown', ...k });
      await c.send('Input.dispatchKeyEvent', { type: 'keyUp', ...k });
      console.log('key', key);
      break;
    }
    default:
      console.log('commands: tabs | info | nav <url> | eval <js> | shot <file> | click <sel> | mouse <x> <y> [click|down|up|mousemove] | key <key>');
  }
} catch (e) { console.error('ERR:', e.message); process.exit(1); }
process.exit(0);
