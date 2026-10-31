"""Job radar: new remote / visa-sponsored jobs, scored by the local model, sent to the phone.

  jobs.py          fetch → filter → score. score >= alert_at: instant alert with Open/Track buttons;
                   digest_at..alert_at-1: queued for the evening digest
  jobs.py digest   send the queue as one numbered message

Track: the button publishes "track <id>" to the [capture] topic; capture.py calls track() here.
From the digest, send "track 3" to the same topic to track line 3.
"""
import datetime as dt
import sys

from common import cfg, load, now, odysseus, save
from common import notify as _notify
from job_score import DEFAULTS, hard_filter, score
from job_sources import fetch_all

MAX_SCORED = 40  # ~30 s each on the iGPU; the rest wait in the backlog for the next run
KEEP_DAYS = 60   # forget seen ids after this


def notify(*a, **kw):  # job messages go to their own topic when [jobs].topic is set
    _notify(*a, topic=cfg()["jobs"].get("topic"), **kw)


def jcfg():
    return {**DEFAULTS, "alert_at": 8, "digest_at": 5, **cfg()["jobs"]}


def key(j):  # the same job often appears on a job board and on the company's own ATS
    return f"{j['company']}|{j['title']}".lower()


def summary(j, s):
    lane = f"Visa ✓ {s['country']}" if s["visa"] and s["country"] else "Remote" if s["remote_ok"] else "?"
    pay = f" · ${s['usd_year'] // 1000}k" if s["usd_year"] else ""
    return f"**{j['company']}** · {j['location'][:60]} · {lane}{pay}"


def alert(j, s):
    c = cfg()
    topic_url = f"{c.get('ntfy_public_url', c['ntfy_url'])}/{c['capture']['topic']}"
    gap = f"\nGap: {s['gap']}" if s["gap"] else ""
    notify(f"🔥 {s['score']}/10 · {j['title'][:80]}", f"{summary(j, s)}\nWhy: {s['why']}{gap}",
           priority=4, tags=["briefcase"], click=j["url"], actions=[
               {"action": "view", "label": "Open", "url": j["url"]},
               {"action": "copy", "label": "Copy link", "value": j["url"]},
               {"action": "http", "label": "Track", "url": topic_url, "method": "POST",
                "body": f"track {j['id']}", "clear": True}])


def run():
    jc, today = jcfg(), now().date().isoformat()
    seen, info, queue = load("jobs_seen.json", {}), load("jobs_info.json", {}), load("jobs_digest.json", [])
    jobs, errors = fetch_all(jc)
    fresh = {}
    for j in load("jobs_backlog.json", []) + jobs:  # backlog: passed filters, not scored yet (HN won't resend them)
        if j["id"] not in seen and key(j) not in seen:
            fresh.setdefault(key(j), j)
    kept = []
    for j in fresh.values():
        if reason := hard_filter(j, jc):
            seen[j["id"]] = today
            print(f"skip {j['id']}: {reason}")
        else:
            kept.append(j)
    kept.sort(key=lambda j: j.get("posted") or "", reverse=True)
    save("jobs_backlog.json", kept[MAX_SCORED:])
    for j in kept[:MAX_SCORED]:
        s = score(j, jc)
        print(f"{s['score']}/10 {j['id']} {j['title']} @ {j['company']}")
        info[j["id"]] = {"title": j["title"], "company": j["company"], "url": j["url"], "why": s["why"]}
        if s["score"] >= jc["alert_at"]:
            alert(j, s)
        elif s["score"] >= jc["digest_at"]:
            queue.append({"id": j["id"], "score": s["score"], "line": f"{s['score']}/10 [{j['title'][:60]}]({j['url']}) · {summary(j, s)}"})
        seen[j["id"]] = seen[key(j)] = today
        for name, data in (("jobs_seen.json", seen), ("jobs_info.json", info), ("jobs_digest.json", queue)):
            save(name, data)  # after every job: a crash mid-run doesn't re-alert
    cutoff = (now().date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    seen = {k: d for k, d in seen.items() if d >= cutoff}
    save("jobs_seen.json", seen)
    save("jobs_info.json", {k: v for k, v in info.items() if k in seen})
    save("jobs_errors.json", errors)
    print(f"{len(jobs)} fetched, {len(fresh)} new, {len(kept)} passed filters, errors: {errors or 'none'}")


def digest():
    queue = sorted(load("jobs_digest.json", []), key=lambda q: -q["score"])[:15]
    errors = load("jobs_errors.json", [])
    if not queue and not errors:
        return
    lines = [f"{n}. {q['line']}" for n, q in enumerate(queue, 1)]
    if queue:
        lines.append("\nTrack one: send `track <number>` to your inbox topic.")
    if errors:
        lines.append("Sources down: " + "; ".join(errors))
    notify(f"📋 Jobs today: {len(queue)} maybe", "\n".join(lines), tags=["clipboard"])
    save("jobs_last_digest.json", [q["id"] for q in queue])
    save("jobs_digest.json", [])


def track(ref):
    """"track <id>" from an alert button, or "track <n>" for line n of the last digest → Odysseus todo."""
    ref = ref.strip()
    if ref.isdigit():
        ids = load("jobs_last_digest.json", [])
        ref = ids[int(ref) - 1] if 0 < int(ref) <= len(ids) else ""
    j = load("jobs_info.json", {}).get(ref)
    if not j:
        notify("⚠️ Track failed", f"Unknown job `{ref}`", tags=["warning"])
        return
    due = (now() + dt.timedelta(days=2)).replace(hour=13, minute=0, second=0, microsecond=0)
    odysseus("/todos", {"action": "add", "title": f"Apply: {j['company']} – {j['title']}"[:80],
                        "content": f"{j['url']}\n{j['why']}", "due_date": due.isoformat(), "label": "Jobs"})
    notify(f"📌 Tracking: {j['company']}", f"{j['title']}\nTodo due {due:%a %-d %b}", tags=["pushpin"])


if __name__ == "__main__":
    digest() if sys.argv[1:] == ["digest"] else run()
