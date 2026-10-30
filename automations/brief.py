"""12:30 brief: today's calendar, Notion deadlines, todos, portal status. Qwen adds a 2-line focus."""
import datetime as dt

from common import cfg, fmt_time, has_token, llm, load, notify, now, odysseus


def due(x):
    return dt.date.fromisoformat(x["due"][:10]) if x.get("due") else None


def calendar_today(t):
    start = t.replace(hour=0, minute=0, second=0, microsecond=0)
    events = odysseus(f"/calendar/events?start={start.isoformat()}&end={(start + dt.timedelta(days=1)).isoformat()}")["events"]
    out = []
    for e in sorted(events, key=lambda e: e.get("dtstart", "")):
        if e.get("summary", "").startswith("Due: "):
            continue  # deadlines are listed from Notion below
        when = "all day" if e.get("all_day") else fmt_time(dt.datetime.fromisoformat(e["dtstart"]).astimezone())
        out.append(f"- **{when}** {e.get('summary', '(no title)')}")
    return out


def main():
    t = now()
    today = t.date()
    sections = []

    if has_token():
        try:
            cal = calendar_today(t)
            sections.append("**📅 Calendar**\n" + ("\n".join(cal) if cal else "- Nothing on the calendar"))
        except Exception as e:
            sections.append(f"**📅 Calendar** unavailable ({e})")

    snap = load("notion_tasks.json", {"tasks": [], "synced_at": None})
    open_ = [x for x in snap["tasks"] if not x.get("done") and due(x)]
    buckets = [
        ("🔥 Overdue", [x for x in open_ if due(x) < today]),
        ("⏰ Due today", [x for x in open_ if due(x) == today]),
        ("📌 Tomorrow", [x for x in open_ if due(x) == today + dt.timedelta(days=1)]),
        ("🗓️ This week", [x for x in open_ if today + dt.timedelta(days=1) < due(x) <= today + dt.timedelta(days=7)]),
    ]
    dl = []
    for name, items in buckets:
        if items:
            dl.append(f"**{name}**\n" + "\n".join(f"- [{x['title']}]({x['url']}) · {due(x):%a %-d %b}" for x in sorted(items, key=due)))
    if snap["synced_at"]:
        age = t - dt.datetime.fromisoformat(snap["synced_at"])
        stale = f"\n\n> Notion last read {int(age.total_seconds() // 3600)}h ago" if age > dt.timedelta(hours=6) else ""
        sections.append("\n\n".join(dl) + stale if dl else "**✅ No Notion deadlines this week**" + stale)
    else:
        sections.append("> Notion not connected yet")

    wd = load("watchdog.json", {"urls": {}, "incidents": []})
    since = t - dt.timedelta(hours=24)
    for p in cfg().get("project", []):
        down_now = wd["urls"].get("project:" + p["name"], {}).get("down_since")
        recent = [i for i in wd["incidents"] if i["project"] == p["name"] and dt.datetime.fromisoformat(i["end"]) > since]
        if down_now:
            sections.append(f"**🔴 {p['label']} is down right now**")
        elif recent:
            sections.append(f"**⚠️ {p['label']}** had {len(recent)} outage(s) in the last 24h")

    urgent = buckets[0][1] + buckets[1][1] + buckets[2][1]
    if urgent:
        try:
            focus = llm("Deadlines:\n" + "\n".join(f"- {x['title']} due {x['due'][:10]}" for x in urgent)
                        + f"\nToday is {today:%A %Y-%m-%d}.",
                        "Write exactly 2 short bullets starting with '- ' telling a developer what to tackle first "
                        "today and why, based only on the deadlines given. No preamble.", max_tokens=120)
            sections.insert(0, "**🎯 Focus**\n" + focus)
        except Exception:
            pass  # the brief still goes out without the focus lines

    notify(f"☀️ {t:%A %-d %b}", "\n\n".join(sections), tags=["sunny"])


if __name__ == "__main__":
    main()
