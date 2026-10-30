"""Phone capture: anything published to the ntfy [capture].topic lands in Odysseus.

  text  ("call the bank tomorrow 4pm")  → todo, reminder at that time
  link  (shared from the phone)     → Qwen summary saved as an Odysseus Document

Long-running (systemd service, restarts on failure). Replies go to the normal Reminders topic, never back to inbox.
"""
import datetime as dt
import html
import json
import re
import urllib.request

from common import cfg, fmt_time, http, llm, load, notify, odysseus, save, todo_from_text

URL = re.compile(r"https?://\S+")


def page_text(url):
    status, page = http(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    title = html.unescape(m.group(1)).strip() if m else url
    body = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>|<[^>]+>", " ", page, flags=re.S | re.I)
    return title[:150], re.sub(r"\s+", " ", html.unescape(body))[:6000]


def handle(text):
    if m := URL.search(text):
        url = m.group(0)
        try:
            title, body = page_text(url)
        except Exception as e:
            notify("⚠️ Couldn't read link", f"{url}\n{e}", tags=["warning"])
            return
        summary = llm(f"Page: {title}\n\n{body}", system="Summarise this web page in 3-5 short bullet points. "
                      "Plain facts only, no intro.", max_tokens=300)
        odysseus("/documents", {"title": title, "language": "markdown", "content": f"{url}\n\n{summary}"})
        notify(f"📄 Saved: {title}", summary[:600], tags=["page_facing_up"])
    else:
        todo = todo_from_text(text, "The text is a note the reader typed for themselves; keep their wording.")
        odysseus("/todos", {"action": "add", "title": todo["title"], "due_date": todo["due"], "label": "Phone"})
        when = dt.datetime.fromisoformat(todo["due"]) if todo["due"] else None
        notify(f"✅ Todo: {todo['title']}",
               f"Reminder {when:%a %-d %b}, {fmt_time(when)}" if when else "No reminder time", tags=["white_check_mark"])


def main():
    c = cfg()
    st = load("capture.json", {})
    url = f"{c['ntfy_url']}/{c['capture']['topic']}/json" + (f"?since={st['last']}" if st.get("last") else "")
    # ntfy sends a keepalive every 45 s; a dead connection times out and systemd restarts us, resuming at `last`
    with urllib.request.urlopen(url, timeout=120) as stream:
        for line in stream:
            ev = json.loads(line)
            if ev.get("event") != "message":
                continue
            try:
                handle(ev.get("message", ""))
            except Exception as e:
                notify("⚠️ Capture failed", f"{ev.get('message', '')[:200]}\n{str(e)[:300]}", priority=4, tags=["warning"])
            save("capture.json", {"last": ev["id"]})


if __name__ == "__main__":
    main()
