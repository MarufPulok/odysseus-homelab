"""Read my tasks off a Notion board (guest login, browser) and mirror due dates into the Odysseus calendar.

Odysseus then sends the reminders itself (day before, 1 PM) through its ntfy channel.
"""
import datetime as dt

from common import cfg, has_token, load, notify, now, odysseus, save
from notion_scrape import scrape

REMIND_MIN = 11 * 60  # all-day event starts 00:00, so 660 min before = 1 PM the day before


def main():
    t = now()
    try:
        rows = scrape()
    except Exception as e:
        st = load("notion_errors.json", {"count": 0})
        st["count"] += 1
        save("notion_errors.json", st)
        if st["count"] in (2, 10):  # say so once it's clearly broken, not on one blip
            notify("⚠️ Notion sync failing", f"{st['count']} runs in a row: {e}\nThe Notion login on the Dell may have expired.",
                   priority=4, tags=["warning"])
        raise
    save("notion_errors.json", {"count": 0})

    done_names = {s.lower() for s in cfg()["notion"]["done_statuses"]}
    prev = {x["id"]: x for x in load("notion_tasks.json", {"tasks": []})["tasks"]}
    tasks = []
    for r in rows:
        p = prev.get(r["id"], {})
        r["done"] = r.get("status", "").lower() in done_names
        # Finish date: the moment we saw it flip to done; on first sight, Notion's "Completed on" or last edit.
        if r["done"] and not p.get("done_at"):
            seen_open = p and not p.get("done")  # we watched it flip: that moment is the truth
            r["done_at"] = t.isoformat() if seen_open else (r.get("finished_on") or r.get("edited"))
        else:
            r["done_at"] = p.get("done_at") if r["done"] else None
        tasks.append(r)
    save("notion_tasks.json", {"synced_at": t.isoformat(), "tasks": tasks})

    if has_token():
        sync_calendar(tasks, t)


def sync_calendar(tasks, t):
    events = load("notion_events.json", {})  # task id -> {"uid", "due"}
    today = t.date().isoformat()
    want = {x["id"]: x for x in tasks if not x.get("done") and x.get("due") and x["due"][:10] >= today}
    for tid, ev in list(events.items()):
        if tid not in want or want[tid]["due"][:10] != ev["due"]:
            try:
                odysseus(f"/calendar/events/{ev['uid']}", method="DELETE")
            except RuntimeError:
                pass  # already gone (deleted by hand)
            del events[tid]
    for tid, x in want.items():
        if tid in events:
            continue
        created = odysseus("/calendar/events", {
            "summary": f"Due: {x['title']}", "dtstart": x["due"][:10], "all_day": True,
            "description": x.get("url", ""), "reminder_minutes": REMIND_MIN,
        })
        uid = (created or {}).get("uid") or (created or {}).get("event", {}).get("uid")
        events[tid] = {"uid": uid, "due": x["due"][:10]}
    save("notion_events.json", events)


if __name__ == "__main__":
    main()
