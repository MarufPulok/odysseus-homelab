"""Meeting prep: 10-20 min before a calendar event that names a project, push that project's open Notion items."""
import datetime as dt

from common import caldav_pull, cfg, has_token, load, notify, now, odysseus, save


def main():
    if not has_token():
        return
    caldav_pull()  # runs every 10 min, so this also keeps the brief's calendar fresh
    t = now()
    events = odysseus(f"/calendar/events?start={t.isoformat()}&end={(t + dt.timedelta(minutes=25)).isoformat()}")["events"]
    sent = load("prep_sent.json", {})
    snap = load("notion_tasks.json", {"tasks": []})
    for e in events:
        if e.get("all_day") or e.get("summary", "").startswith("Due: "):
            continue
        start = dt.datetime.fromisoformat(e["dtstart"]).astimezone()
        key = f"{e.get('uid')}|{start.isoformat()}"
        if key in sent or not dt.timedelta(minutes=5) <= start - t <= dt.timedelta(minutes=20):
            continue
        title = e.get("summary", "")
        projects = [p for p in cfg().get("project", [])
                    if p["name"].lower() in title.lower() or p.get("label", "").lower() in title.lower()]
        mins = round((start - t).total_seconds() / 60)
        lines = []
        for p in projects:
            items = [x for x in snap["tasks"] if not x.get("done") and x.get("project", "").lower() == p["notion_project"].lower()]
            items.sort(key=lambda x: x.get("due") or "9999")
            lines.append(f"{p['label']}: {len(items)} open\n" + "\n".join(
                f"• {x['title']}" + (f" (due {x['due'][:10]})" if x.get("due") else "") for x in items[:10]))
        notify(f"🗣️ {title} in {mins} min", "\n\n".join(lines) or "No project matched this meeting's title, so no Notion items.",
               priority=4, tags=["speech_balloon"])
        sent[key] = t.isoformat()
    save("prep_sent.json", {k: v for k, v in sent.items() if t - dt.datetime.fromisoformat(v) < dt.timedelta(days=2)})


if __name__ == "__main__":
    main()
