"""Shared helpers for the Dell automations: config, state, ntfy, Ollama, Odysseus, Slack."""
import datetime as dt
import json
import pathlib
import subprocess
import tomllib
import urllib.error
import urllib.parse
import urllib.request

HOME = pathlib.Path(__file__).resolve().parent
STATE = HOME / "state"
STATE.mkdir(exist_ok=True)
TOKEN_FILE = pathlib.Path.home() / ".config/automations/odysseus-token"
CONTAINER = "odysseus-odysseus-1"  # docker compose default for a clone named "odysseus"


def cfg():
    return tomllib.loads((HOME / "config.toml").read_text())


def now():
    return dt.datetime.now().astimezone()


def load(name, default):
    p = STATE / name
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(name, data):
    p = STATE / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str))
    tmp.replace(p)


def http(url, body=None, headers=None, method=None, timeout=20):
    """Return (status, text). Network errors come back as (0, reason)."""
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": "dell-automations/1"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # DNS, TLS, timeout, refused
        return 0, f"{type(e).__name__}: {e}"


def notify(title, message, priority=3, tags=None, click=None, copy=None):
    """Markdown message to the phone. `copy` adds a button that puts that text on the clipboard (for Slack)."""
    c = cfg()
    body = {"topic": c["ntfy_topic"], "title": title, "message": message[:4000],
            "priority": priority, "tags": tags or [], "markdown": True}
    if click:
        body["click"] = click
    if copy:
        body["actions"] = [{"action": "copy", "label": "Copy for Slack", "value": copy[:3000]}]
    status, text = http(c["ntfy_url"], body)
    if status != 200:
        raise RuntimeError(f"ntfy publish failed: {status} {text[:200]}")


def llm(prompt, system="You are a concise assistant.", max_tokens=700, fmt=None):
    """Local Qwen via Ollama. Slow (~8 tok/s) but free and private; only used by scheduled jobs.
    fmt="json" makes Ollama return valid JSON."""
    c = cfg()
    status, text = http(c["ollama_url"] + "/api/chat", {
        "model": c["ollama_model"], "stream": False,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "options": {"temperature": 0.3, "num_predict": max_tokens, "num_ctx": 8192},
        **({"format": fmt} if fmt else {}),
    }, timeout=1200)
    if status != 200:
        raise RuntimeError(f"ollama failed: {status} {text[:200]}")
    return json.loads(text)["message"]["content"].strip()


def todo_from_text(text, rules=""):
    """Qwen turns free text into {"action": bool, "title": str, "due": ISO-with-offset | None}.
    Odysseus parses bare times like "4pm" as UTC for API calls, so the offset is attached here."""
    t = now()
    days = "\n".join(f"{(t + dt.timedelta(days=i)):%a %Y-%m-%d}" + (" (today)" if i == 0 else " (tomorrow)" if i == 1 else "")
                     for i in range(8))
    out = llm(f"Now: {t:%a %Y-%m-%d %H:%M}\nCalendar:\n{days}\n\nText:\n{text[:3000]}", fmt="json", max_tokens=200, system=(
        rules + ' Turn the text into a todo for the reader. Reply with JSON only: {"action": true|false, "title": "...", '
        '"when": "...", "due": "YYYY-MM-DD HH:MM" or null}. "action" is false only when nothing needs doing '
        '(thanks, FYI, chit-chat). "title": short imperative, max 80 chars, in English. "when": the exact words of the '
        'text that name a time or day (like "tomorrow 3pm", "friday"), or "" if there are none. "due": null when '
        '"when" is "", else that moment; a day without a time means 13:00. Read dates from the calendar above.'))
    try:
        j = json.loads(out)
    except json.JSONDecodeError:
        return {"action": True, "title": text.strip().splitlines()[0][:80], "due": None}
    due = None
    when = str(j.get("when") or "").strip().lower()
    if j.get("due") and when and when in text.lower():  # Qwen likes to invent "now" as a due time
        try:
            due = dt.datetime.strptime(str(j["due"]).strip()[:16], "%Y-%m-%d %H:%M").replace(tzinfo=t.tzinfo).isoformat()
        except ValueError:
            pass
    return {"action": bool(j.get("action", True)), "title": str(j.get("title") or text)[:80].strip(), "due": due}


SLACK_SESSION = pathlib.Path.home() / ".config/automations/slack-session.json"


def slack(method, **params):
    """Slack web API as me, with the browser session copied into SLACK_SESSION (token + `d` cookie)."""
    s = json.loads(SLACK_SESSION.read_text())
    t = s["teams"][0]
    req = urllib.request.Request(f"https://{t['domain']}.slack.com/api/{method}",
                                 data=urllib.parse.urlencode({"token": t["token"], **params}).encode(),
                                 headers={"Cookie": "d=" + s["d"], "User-Agent": "dell-automations/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    if not out.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {out.get('error')} (signed out? copy the session again from Chrome)")
    return out, t


def odysseus(path, body=None, method=None):
    """Scoped Odysseus API (/api/codex/*) with the Claude Agent token."""
    token = TOKEN_FILE.read_text().strip()
    status, text = http(cfg()["odysseus_url"] + "/api/codex" + path, body,
                        {"Authorization": f"Bearer {token}"}, method)
    if not 200 <= status < 300:
        raise RuntimeError(f"odysseus {path}: {status} {text[:200]}")
    return json.loads(text) if text.strip() else None


def caldav_pull():
    """Odysseus only pulls Google Calendar when its Calendar page is opened, so pull it ourselves. Best effort."""
    code = "import asyncio; from src.caldav_sync import sync_caldav_direction as s; print(asyncio.run(s('admin', 'pull')))"
    try:
        subprocess.run(["docker", "exec", "-w", "/app", cfg().get("odysseus_container", CONTAINER), "python", "-c", code],
                       capture_output=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        pass  # stale calendar beats a crashed job


def has_token():
    return TOKEN_FILE.exists() and TOKEN_FILE.read_text().strip() != ""


def fmt_time(t):
    return t.strftime("%-I:%M %p")
