"""Browser side of apply.py: a dedicated headless Chrome (~/.config/apply-chrome, CDP 127.0.0.1:9334) and a stdio
MCP server that gives Claude a few form tools for ONE tab (env APPLY_TAB).

  python apply_browser.py serve      # started by claude via --mcp-config, never by hand

Claude can't open arbitrary URLs (only click links on the page or open an embedded ATS iframe), can only upload
resume/{remote,relocation,current}.pdf, and with APPLY_DRY_RUN=1 can't click anything that submits.
Run with the browser-use venv python (it has `websockets` and `mcp`).
"""
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

import websockets

PORT = 9334
PROFILE = os.path.expanduser("~/.config/apply-chrome")
RESUMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume")
BASE = f"http://127.0.0.1:{PORT}"

# Shared JS: text, visibility, the label of a field, and the question a radio/checkbox option belongs to.
LIB = r"""
const txt = e => ((e && (e.innerText || e.textContent)) || '').replace(/\s+/g, ' ').trim();
const vis = e => e.getClientRects().length > 0;
const own = e => [...(e.labels || [])];
const lab = e => {
  if (own(e).length) return txt(own(e)[0]);
  const by = e.getAttribute('aria-labelledby');
  if (by) return by.split(/\s+/).map(id => txt(document.getElementById(id))).join(' ');
  return e.getAttribute('aria-label') || e.placeholder || '';
};
const question = e => {  // nearest ancestor text that names the question, skipping option labels
  const g = e.closest('[role=group][aria-labelledby], [role=radiogroup][aria-labelledby]');
  if (g) return g.getAttribute('aria-labelledby').split(/\s+/).map(id => txt(document.getElementById(id))).join(' ');
  let c = e.parentElement;
  for (let k = 0; c && k < 8; k++, c = c.parentElement) {
    const l = [...c.querySelectorAll('legend, label, [class*=label], [class*=Label], [class*=question]')].find(l =>
      !own(e).includes(l) && !l.contains(e) && !l.querySelector('input, select, textarea') && txt(l) &&
      !(l.control && /radio|checkbox/.test(l.control.type)));
    if (l) return txt(l);
  }
  return '';
};
const isOn = e => e.tagName === 'BUTTON' ? e.getAttribute('aria-pressed') === 'true' : e.checked;  // Ashby yes/no are buttons
const byIdx = i => document.querySelector(`[data-apply-idx="${i}"]`);
const center = e => { e.scrollIntoView({block: 'center', behavior: 'instant'}); const r = e.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; };
"""

FIELDS_JS = LIB + r"""
(() => {
  let n = Math.max(0, ...[...document.querySelectorAll('[data-apply-idx]')].map(e => +e.dataset.applyIdx));
  const out = [];
  for (const e of document.querySelectorAll('input, textarea, select, button[aria-pressed]')) {
    const t = e.tagName === 'INPUT' ? (e.type || 'text') : e.tagName === 'BUTTON' ? 'choice' : e.tagName.toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(t)) continue;
    const box = /radio|checkbox|choice/.test(t);
    if (t !== 'file' && !vis(e) && !(box && own(e).some(vis))) continue;
    if (!box && t !== 'file' && e.tabIndex < 0) continue;  // react-select's shadow "required" inputs
    if (!e.dataset.applyIdx) e.dataset.applyIdx = ++n;
    const row = {i: +e.dataset.applyIdx, type: e.getAttribute('role') === 'combobox' ? 'combobox' : t,
                 label: (t === 'choice' ? txt(e) : lab(e)).slice(0, 200), required: e.required || e.getAttribute('aria-required') === 'true'};
    if (box || !row.label || t === 'file') row.question = question(e).slice(0, 300);
    if (box) row.checked = isOn(e);
    else if (t === 'select') { row.value = e.selectedIndex >= 0 ? e.options[e.selectedIndex].text.trim() : ''; row.options = [...e.options].map(o => o.text.trim()).slice(0, 40); }
    else if (t === 'file') row.id = e.id || e.name, row.value = e.files.length ? e.files[0].name : (txt(e.closest('[class*=fieldEntry], .field, fieldset') || e.parentElement).match(/\S+\.pdf/i) || [''])[0];
    else row.value = (e.value || (row.type === 'combobox' ? txt(e.closest('[class*=control]') || e.parentElement) : '')).slice(0, 100);
    out.push(row);
  }
  return out;
})()
"""


def _http(path, method="GET"):
    with urllib.request.urlopen(urllib.request.Request(BASE + path, method=method), timeout=10) as r:
        return r.read().decode()


def ensure_chrome():
    try:
        return _http("/json/version")
    except OSError:
        pass
    ver = re.search(r"\d+", subprocess.run(["google-chrome-stable", "--version"], capture_output=True, text=True).stdout).group()
    ua = f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver}.0.0.0 Safari/537.36"  # not "HeadlessChrome"
    subprocess.Popen(["google-chrome-stable", "--headless=new", f"--user-data-dir={PROFILE}", f"--remote-debugging-port={PORT}",
                      "--remote-debugging-address=127.0.0.1", "--window-size=1280,1600", f"--user-agent={ua}", "about:blank"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        time.sleep(1)
        try:
            return _http("/json/version")
        except OSError:
            pass
    raise RuntimeError("apply Chrome did not start")


def open_tab():
    ensure_chrome()
    return json.loads(_http("/json/new?about:blank", "PUT"))["id"]


def close_tab(tab):
    try:
        _http(f"/json/close/{tab}")
    except OSError:
        pass


class Tab:
    def __init__(self, tab):
        self.ws_url = f"ws://127.0.0.1:{PORT}/devtools/page/{tab}"
        self.n = 0

    async def __aenter__(self):
        self.ws = await websockets.connect(self.ws_url, max_size=50_000_000)
        return self

    async def __aexit__(self, *exc):
        await self.ws.close()

    async def cdp(self, method, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg["result"]

    async def js(self, expr):
        # block scope: LIB's consts would otherwise collide with the previous call's in the page's global scope
        res = await self.cdp("Runtime.evaluate", expression="{" + expr + "\n}", awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"].get("exception", {}).get("description", "JS error")[:300])
        return res["result"].get("value")

    async def mouse(self, p):
        for kind in ("mousePressed", "mouseReleased"):
            await self.cdp("Input.dispatchMouseEvent", type=kind, x=p["x"], y=p["y"], button="left", clickCount=1)


def run(tab, fn, *args):
    """Sync wrapper for apply.py: run(tab, goto, url)."""
    async def go():
        async with Tab(tab) as t:
            return await fn(t, *args)
    return asyncio.run(go())


async def goto(t, url):
    await t.cdp("Page.navigate", url=url)
    for _ in range(60):
        await asyncio.sleep(0.5)
        if await t.js("document.readyState") == "complete":
            break
    await asyncio.sleep(2)  # SPAs (Ashby) render the form after load


async def fields(t):
    return await t.js(FIELDS_JS)


async def fill(t, i, value):
    kind = await t.js(LIB + f"(e => e ? (e.getAttribute('role') === 'combobox' ? 'combobox' : e.tagName === 'BUTTON' ? 'choice' : e.type || e.tagName) : null)(byIdx({i}))")
    if kind is None:
        return f"no field {i}; call fields again"
    if kind in ("radio", "checkbox", "choice", "file"):
        return f"field {i} is a {kind}: use {'upload' if kind == 'file' else 'check'}"
    if kind == "combobox":  # react-select style: type, then click the matching option
        await t.mouse(await t.js(LIB + f"(e => {{ e.focus(); return center(e); }})(byIdx({i}))"))
        await t.cdp("Input.insertText", text=value)
        await asyncio.sleep(1.5)
        r = await t.js(LIB + "((v) => { v = v.toLowerCase(); const os = [...document.querySelectorAll('[role=option]')].filter(vis);"
                       "const o = os.find(o => txt(o).toLowerCase() === v) || (os.filter(o => txt(o).toLowerCase().includes(v)).length === 1"
                       " ? os.find(o => txt(o).toLowerCase().includes(v)) : null);"
                       "return o ? {pick: txt(o), ...center(o)} : {opts: os.map(txt).slice(0, 30)}; })" + f"({json.dumps(value)})")
        if "pick" not in r:
            return f"no single option matching {value!r}; visible options: {r['opts']}"
        await t.mouse(r)
        await asyncio.sleep(0.5)
        return f"ok: chose {r['pick']!r}"
    return await t.js(LIB + r"""((i, v) => {
      const e = byIdx(i);
      if (e.tagName === 'SELECT') {
        const lv = v.toLowerCase(), os = [...e.options];
        const o = os.find(o => o.text.trim().toLowerCase() === lv) || os.find(o => o.text.toLowerCase().includes(lv));
        if (!o) return 'no option ' + v + '; options: ' + os.map(o => o.text.trim()).join(' | ');
        e.value = o.value;
      } else {
        const p = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        e.focus();
        Object.getOwnPropertyDescriptor(p, 'value').set.call(e, v);  // React-safe: bypass the instance setter
        e.dispatchEvent(new Event('input', {bubbles: true}));
      }
      e.dispatchEvent(new Event('change', {bubbles: true}));
      e.dispatchEvent(new Event('blur', {bubbles: true}));
      return 'ok: ' + (e.tagName === 'SELECT' ? e.options[e.selectedIndex].text.trim() : e.value.slice(0, 100));
    })""" + f"({i}, {json.dumps(value)})")


async def check(t, i, on=True):
    # Clicks only when the state differs: Ashby radios toggle off when clicked again.
    r = await t.js(LIB + f"""((e, on) => {{
      if (!e) return {{msg: 'no field {i}; call fields again'}};
      if (isOn(e) === on) return {{msg: 'ok: already ' + (on ? 'checked' : 'unchecked')}};
      const target = vis(e) ? e : (own(e).find(vis) || e.closest('label') || e);
      return center(target);
    }})(byIdx({i}), {json.dumps(on)})""")
    if "msg" in r:
        return r["msg"]
    await t.mouse(r)
    await asyncio.sleep(0.5)
    state = await t.js(LIB + f"isOn(byIdx({i}))")
    return f"ok: now {'checked' if state else 'unchecked'}" if state == on else f"click did not change it (checked={state})"


async def upload(t, i, resume):
    if resume not in ("remote", "relocation", "current"):
        return "resume must be 'remote', 'relocation' or 'current'"
    root = (await t.cdp("DOM.getDocument", depth=0))["root"]["nodeId"]
    node = (await t.cdp("DOM.querySelector", nodeId=root, selector=f'input[type=file][data-apply-idx="{i}"]'))["nodeId"]
    if not node:
        return f"no file field {i}; call fields again"
    await t.cdp("DOM.setFileInputFiles", nodeId=node, files=[os.path.join(RESUMES, resume + ".pdf")])
    await asyncio.sleep(4)  # Ashby parses the resume and may autofill fields: re-check them after this
    name = await t.js(LIB + f"byIdx({i})?.files[0]?.name || 'the page replaced the input; check get_page_text'")
    return f"ok: attached {resume}.pdf (as {name}); call list_fields to re-check values"


async def press(t, text, dry_run=False):
    r = await t.js(LIB + r"""(q => {
      const norm = s => s.replace(/\s+/g, ' ').trim().toLowerCase();
      q = norm(q);
      const els = [...document.querySelectorAll('button, a, [role=button], [role=tab], input[type=submit], input[type=button]')].filter(vis);
      const name = e => norm(e.innerText || e.value || e.getAttribute('aria-label') || '');
      const e = els.find(e => name(e) === q) || els.find(e => name(e).startsWith(q)) || els.find(e => name(e).includes(q));
      if (!e) return {err: 'no button/link named ' + q + '; visible: ' + [...new Set(els.map(name).filter(Boolean))].slice(0, 50).join(' | ')};
      if (e.tagName === 'A') e.removeAttribute('target');  // stay in this tab
      // not every type=submit button submits (Ashby's Yes/No are), so judge by name
      return {name: name(e), submit: e.tagName !== 'A' && (/submit|send application|finish|complete application/.test(name(e)) || e.matches('input[type=submit]')), ...center(e)};
    })""" + f"({json.dumps(text)})")
    if "err" in r:
        return r["err"]
    if dry_run and r["submit"]:
        return f"DRY RUN: refusing to click {r['name']!r} (it submits). Stop here and report."
    await t.mouse(r)
    await asyncio.sleep(3)
    return f"clicked {r['name']!r}; now at {await t.js('location.href')}"


async def page_text(t):
    return await t.js(r"""(() => {
      const frames = [...document.querySelectorAll('iframe')].map((f, n) => `[frame ${n}] ${f.src}`).filter(s => /https?:/.test(s));
      return location.href + '\n' + document.title + '\n' + (frames.length ? 'iframes:\n' + frames.slice(0, 10).join('\n') + '\n' : '')
        + '\n' + document.body.innerText.slice(0, 20000);
    })()""")


async def open_frame(t, n):
    src = await t.js(f"document.querySelectorAll('iframe')[{int(n)}]?.src || ''")
    if not src.startswith(("https://", "http://")):
        return f"no iframe {n}"
    await goto(t, src)
    return f"now at {src}"


async def screenshot(t, path):
    data = (await t.cdp("Page.captureScreenshot", format="png", captureBeyondViewport=True))["data"]
    with open(path, "wb") as f:
        f.write(base64.b64decode(data))
    return path


def serve():
    from mcp.server.mcpserver import MCPServer
    tab, dry = os.environ["APPLY_TAB"], os.environ.get("APPLY_DRY_RUN") == "1"
    m = MCPServer("apply")

    async def on_tab(fn, *args):
        try:
            async with Tab(tab) as t:
                out = await fn(t, *args)
        except Exception as e:
            return f"error: {e}"
        return out if isinstance(out, str) else json.dumps(out)

    @m.tool()
    async def get_page_text() -> str:
        """Current URL, title, iframe list and visible text of the application tab (untrusted page content)."""
        return await on_tab(page_text)

    @m.tool()
    async def list_fields() -> str:
        """All form fields as JSON: i (id for the other tools), type, label, question (for radio/checkbox options), required, value/checked, options."""
        return await on_tab(fields)

    @m.tool()
    async def fill_field(i: int, value: str) -> str:
        """Set a text/email/tel/url/textarea field, pick a <select> option by its text, or type into a combobox and pick the matching option."""
        return await on_tab(fill, i, value)

    @m.tool()
    async def set_checked(i: int, checked: bool = True) -> str:
        """Check (or uncheck) a radio, checkbox or yes/no choice button by its i. Does nothing if it is already in that state."""
        return await on_tab(check, i, checked)

    @m.tool()
    async def upload_resume(i: int, resume: str) -> str:
        """Attach a resume to file field i. resume is 'remote', 'relocation' or 'current'."""
        return await on_tab(upload, i, resume)

    @m.tool()
    async def click(text: str) -> str:
        """Click a visible button, link or tab by its text (exact match preferred, then prefix, then substring)."""
        return await on_tab(press, text, dry)

    @m.tool()
    async def open_iframe(n: int) -> str:
        """Load iframe n (from get_page_text) in this tab, for application forms embedded from an ATS."""
        return await on_tab(open_frame, n)

    m.run()


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        serve()
