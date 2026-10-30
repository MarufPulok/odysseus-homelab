"""Tiny CDP client: run JavaScript in the logged-in Notion tab of the notion-bot Chrome (127.0.0.1:9333).

Run with automations/.venv python (pip install websockets).
"""
import asyncio
import json
import os
import subprocess
import time
import urllib.request

import websockets

PORT = 9333
PROFILE = os.path.expanduser("~/.config/notion-bot-chrome")


def _targets():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=5) as r:
        return [t for t in json.load(r) if t["type"] == "page"]


def ensure_browser():
    """Reuse the open notion-bot Chrome, or start it headless with the saved login."""
    try:
        return _targets()
    except OSError:
        subprocess.Popen(["google-chrome-stable", "--headless=new", f"--user-data-dir={PROFILE}",
                          f"--remote-debugging-port={PORT}", "--remote-debugging-address=127.0.0.1",
                          "https://app.notion.com/"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            time.sleep(1)
            try:
                if (t := _targets()):
                    return t
            except OSError:
                pass
        raise RuntimeError("notion-bot Chrome did not start")


async def _eval(ws_url, expr):
    async with websockets.connect(ws_url, max_size=50_000_000) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                res = msg["result"]
                if "exceptionDetails" in res:
                    raise RuntimeError(res["exceptionDetails"].get("exception", {}).get("description", "JS error"))
                return res["result"].get("value")


def notion_api(endpoint, body):
    """POST to Notion's own /api/v3/<endpoint> from inside the logged-in tab (uses its cookies)."""
    tabs = [t for t in ensure_browser() if "notion." in t["url"]]
    if not tabs:
        raise RuntimeError("no Notion tab open in the notion-bot Chrome")
    expr = (f"fetch('/api/v3/{endpoint}', {{method: 'POST', headers: {{'content-type': 'application/json'}}, "
            f"body: JSON.stringify({json.dumps(body)})}}).then(async r => ({{status: r.status, body: await r.text()}}))")
    out = asyncio.run(_eval(tabs[0]["webSocketDebuggerUrl"], expr))
    if out["status"] == 401:
        raise RuntimeError("Notion login expired: run ~/automations/notion-login.sh on the Dell")
    if out["status"] != 200:
        raise RuntimeError(f"Notion {endpoint}: HTTP {out['status']} {out['body'][:200]}")
    return json.loads(out["body"])
