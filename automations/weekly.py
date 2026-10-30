"""Friday status for the team lead: what's done this week, what's next, with Notion links. Written by Qwen."""
import datetime as dt

from common import llm, load, notify, now

SYSTEM = ("You write a developer's end-of-week status update for their team lead. Use exactly this format and nothing else:\n\n"
          "Status update for this week.\n\nWhats done so far:\n• <task title> — <link>\n\n"
          "What will be done next:\n• <task title> (due <date>) — <link>\n\n"
          "Rules: use only the tasks given, keep every title and link exactly, no extra commentary, "
          "short plain titles. If a list is empty write '• Nothing yet'.")


def main():
    t = now()
    week_start = (t - dt.timedelta(days=t.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    snap = load("notion_tasks.json", {"tasks": [], "synced_at": None})
    def when(s):  # "Completed on" is a bare date; our own stamps carry a timezone
        d = dt.datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=t.tzinfo)

    done = [x for x in snap["tasks"] if x.get("done_at") and when(x["done_at"]) >= week_start]
    nxt = sorted((x for x in snap["tasks"] if not x.get("done")), key=lambda x: x.get("due") or "9999")
    if not snap["synced_at"]:
        notify("🗓️ Weekly status", "Notion isn't connected yet, so there's nothing to report.", tags=["calendar"])
        return
    data = ("Done this week:\n" + "\n".join(f"- {x['title']} | {x['url']}" for x in done)
            + "\n\nStill open:\n" + "\n".join(f"- {x['title']} | due {(x.get('due') or 'no date')[:10]} | {x['url']}" for x in nxt[:15]))
    try:
        text = llm(data, SYSTEM, max_tokens=900)
    except Exception as e:  # Qwen down: send the raw list rather than nothing
        text = f"(Qwen unavailable: {e})\n\n{data}"
    phone = text.replace("Whats done so far:", "**✅ Whats done so far:**").replace(
        "What will be done next:", "**➡️ What will be done next:**").replace("• ", "- ")
    notify("🗓️ Weekly status", phone, tags=["calendar"], copy=text)


if __name__ == "__main__":
    main()
