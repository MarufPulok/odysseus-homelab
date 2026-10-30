"""Slack messages for me outside work hours (DMs, group DMs, @mentions) become Odysseus todos, label "Slack".

  slack_todos.py        every 15 min: new off-hours messages → todo when Qwen sees something to do (no ping)
  slack_todos.py dry N  print what the last N days would give, add nothing

Only Qwen (local) reads message text. The todo keeps a short title plus sender and link, never the message itself.
"""
import datetime as dt
import re
import sys

from common import cfg, load, notify, now, odysseus, save, slack, todo_from_text

RULES = ("MOST IMPORTANT: the title must never contain a person's name or any sensitive personal detail "
         "(health, money, legal); write 'a user' instead (\"fix login for John Smith\" → \"Fix login for a user\"). "
         "The text is a Slack message sent to the reader by a colleague or client; the todo is what the reader must do.")
# ponytail: catches titled names only ("Mrs. Rahman"); bare names rely on the prompt rule above
HONORIFIC = re.compile(r"\b(Mr|Mrs|Ms|Miss|Dr|Mx)\.?\s+[A-Z][\w'-]*(\s+[A-Z][\w'-]*)?")


def off_hours(t, c):
    """Work runs work_start → work_end. A shift past midnight (13 → 2) counts 01:00 Saturday as Friday's shift."""
    start, end = c["work_start"], c["work_end"]
    if start < end:  # same-day shift, e.g. 9 → 18
        return t.strftime("%a") in c["off_days"] or not start <= t.hour < end
    shifted = t - dt.timedelta(hours=end)
    return shifted.strftime("%a") in c["off_days"] or shifted.hour < start - end


def messages(days):
    """DMs to me + @mentions of me in the last `days`, newest first, deduplicated."""
    me = slack("auth.test")[0]["user_id"]
    since = (now() - dt.timedelta(days=days)).date() - dt.timedelta(days=1)  # Slack's after: is exclusive
    seen, out = set(), []
    for q in (f"to:me after:{since}", f"<@{me}> after:{since}"):
        for m in slack("search.messages", query=q, count=100, sort="timestamp")[0]["messages"]["matches"]:
            key = f"{m['channel']['id']}:{m['ts']}"
            if m.get("user") != me and key not in seen:
                seen.add(key)
                out.append(m | {"key": key, "me": me})
    return out


def main(dry_days=None):
    c = cfg()["slack_todos"]
    st = load("slack_todos.json", {"done": {}})
    cutoff = now() - dt.timedelta(days=dry_days or 2)
    for m in messages(dry_days or 2):
        t = dt.datetime.fromtimestamp(float(m["ts"])).astimezone()
        if t < cutoff or m["key"] in st["done"] or not off_hours(t, c):
            continue
        ch = m["channel"]
        where = "a DM" if ch.get("is_im") else "a group DM" if ch.get("is_mpim") else f"#{ch.get('name')}"
        who = m.get("username") or m.get("user")
        todo = todo_from_text(m["text"].replace(f"<@{m['me']}>", "@me"), RULES)
        todo["title"] = HONORIFIC.sub("a user", todo["title"])
        if todo["due"]:  # a reminder must never ping at night: move it to the start of the next shift
            due = dt.datetime.fromisoformat(todo["due"])
            while off_hours(due, c):
                due = (due + dt.timedelta(hours=1)).replace(minute=0)
            todo["due"] = due.isoformat()
        if dry_days:
            print(f"{t:%a %H:%M} {where}: {'TODO ' + repr(todo['title']) if todo['action'] else 'skip'} due={todo['due']}")
            continue
        if todo["action"]:
            odysseus("/todos", {"action": "add", "title": todo["title"], "label": "Slack", "due_date": todo["due"],
                                "content": f"From {who} in {where}, {t:%a %-d %b %-I:%M %p}\n{m['permalink']}"})
        st["done"][m["key"]] = t.isoformat()
        save("slack_todos.json", st)
    if not dry_days:  # forget keys older than the search window
        st["done"] = {k: v for k, v in st["done"].items() if dt.datetime.fromisoformat(v) > now() - dt.timedelta(days=4)}
        save("slack_todos.json", st)


if __name__ == "__main__":
    if sys.argv[1:2] == ["dry"]:
        main(int(sys.argv[2]))
        raise SystemExit
    try:
        main()
        save("slack_todos_err.json", {})
    except Exception as e:  # runs every 15 min: alert once per distinct error, not every run
        if load("slack_todos_err.json", {}).get("err") != str(e):
            notify("⚠️ Slack → todos failed", str(e)[:500], priority=4, tags=["warning"])
            save("slack_todos_err.json", {"err": str(e)})
        raise
