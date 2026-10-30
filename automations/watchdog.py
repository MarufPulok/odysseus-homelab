"""Portal watchdog.

  watchdog.py          check every project URL; alert on 2 failures in a row, and on recovery
  watchdog.py report   send the paste-ready nightly status message for projects with nightly_report
"""
import datetime as dt
import json
import subprocess
import sys
import urllib.parse

from common import cfg, fmt_time, http, load, notify, now, save

INTERNET_PROBES = ["https://www.google.com/generate_204", "https://1.1.1.1/"]
FAILS_TO_ALERT = 2
REPORT_HOURS = 24


def via_vercel_edge(url):
    """The Dell's ISP blackholes some Vercel edge IPs (216.198.79.195, 64.29.17.195 on 26 Oct 2026) and DNS rotates
    onto them, faking an outage. Retry through Vercel's main anycast IP; a non-Vercel host gets 404 there, so still fails."""
    host = urllib.parse.urlsplit(url).hostname
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-m", "20", "-w", "%{http_code}",
                        "--resolve", f"{host}:443:76.76.21.21", url], capture_output=True, text=True)
    return 200 <= int(r.stdout or 0) < 400


def url_ok(url):
    status, text = http(url, timeout=20)
    if status == 0 and via_vercel_edge(url):  # couldn't connect at all: our network, not the portal
        print(f"{url}: {text[:80]}; reachable via 76.76.21.21, not counted")
        status, text = 200, '{"status": "ok"}'
    if not 200 <= status < 400:
        print(f"{url}: {text[:120] if not status else status}")
        return False, f"HTTP {status}" if status else text[:120]
    if url.rstrip("/").endswith("/ready"):  # backend readiness: database + redis
        try:
            if json.loads(text).get("status") != "ok":
                return False, "ready check not ok: " + text[:120]
        except json.JSONDecodeError:
            return False, "ready check returned non-JSON"
    return True, ""


def check():
    st = load("watchdog.json", {"urls": {}, "incidents": [], "checks": []})
    t = now()
    if not any(http(u, timeout=10)[0] in (200, 204) for u in INTERNET_PROBES):
        return  # the Dell itself is offline: never blame the portal for that
    st["checks"] = [c for c in st["checks"] if t - dt.datetime.fromisoformat(c) < dt.timedelta(hours=REPORT_HOURS)]
    st["checks"].append(t.isoformat())

    for p in cfg().get("project", []):
        failing = []
        for url in p["checks"]:
            ok, why = url_ok(url)
            u = st["urls"].setdefault(url, {"fails": 0})
            u["fails"] = 0 if ok else u["fails"] + 1
            if u["fails"] >= FAILS_TO_ALERT:
                failing.append(f"{url} ({why})")
        key = "project:" + p["name"]
        ps = st["urls"].setdefault(key, {"down_since": None})
        if failing and not ps["down_since"]:
            ps["down_since"] = t.isoformat()
            notify(f"🔴 {p['label']} is DOWN", "**Failed 2 checks in a row:**\n" + "\n".join(f"- {x}" for x in failing),
                   priority=5, tags=["rotating_light"])
        elif not failing and ps["down_since"]:
            start = dt.datetime.fromisoformat(ps["down_since"])
            mins = max(1, round((t - start).total_seconds() / 60))
            st["incidents"].append({"project": p["name"], "start": ps["down_since"], "end": t.isoformat()})
            ps["down_since"] = None
            notify(f"🟢 {p['label']} is back up", f"Down for about **{mins} min** ({fmt_time(start)} to {fmt_time(t)}).",
                   priority=4, tags=["white_check_mark"])
    st["incidents"] = st["incidents"][-200:]
    save("watchdog.json", st)


def report():
    st = load("watchdog.json", {"urls": {}, "incidents": [], "checks": []})
    t = now()
    since = t - dt.timedelta(hours=REPORT_HOURS)
    # Coverage: did the Dell actually check during the window? Gaps over 30 min are flagged to you, not the client.
    stamps = sorted(dt.datetime.fromisoformat(c) for c in st["checks"] if dt.datetime.fromisoformat(c) > since)
    gaps, prev = [], since
    for s in stamps + [t]:
        if s - prev > dt.timedelta(minutes=30):
            day = (lambda x: f"{x:%a} ") if prev.date() != s.date() else (lambda x: "")
            gaps.append(f"{day(prev)}{fmt_time(prev)}–{day(s)}{fmt_time(s)}")
        prev = s
    stamp = f"{t.day} {t:%b %Y}, {fmt_time(t)} · last {REPORT_HOURS} hours"

    for p in cfg().get("project", []):
        if not p.get("nightly_report"):
            continue
        down = [i for i in st["incidents"] if i["project"] == p["name"] and dt.datetime.fromisoformat(i["end"]) > since]
        ongoing = st["urls"].get("project:" + p["name"], {}).get("down_since")
        if ongoing:
            emoji, headline = "🔴", "currently down"
            points = [f"The portal has been unavailable since {fmt_time(dt.datetime.fromisoformat(ongoing))}.",
                      "Our team is on it. We'll update you as soon as it's back."]
        elif down:
            spans = []
            for i in down:
                a, b = dt.datetime.fromisoformat(i["start"]), dt.datetime.fromisoformat(i["end"])
                spans.append(f"about {max(1, round((b - a).total_seconds() / 60))} minutes ({fmt_time(a)} to {fmt_time(b)})")
            emoji, headline = "⚠️", "brief interruption today"
            points = [f"The portal was unavailable for {', and '.join(spans)}. It has been back to normal since.",
                      "Login and data: working.",
                      "Our team already looked into it. Nothing needed from you."]
        else:
            emoji, headline = "✅", "all good"
            points = ["Website, login, and data all working.", "No downtime. Nothing needed from you."]
        # Slack's own markup (*bold*, _italic_, •) for the copy button; Markdown for the phone.
        slack = f"{emoji} *{p['label']} — {headline}*\n_{stamp}_\n\n" + "\n".join(f"• {x}" for x in points)
        phone = f"**{emoji} {p['label']} — {headline}**\n_{stamp}_\n\n" + "\n".join(f"- {x}" for x in points)
        if gaps:
            phone += "\n\n> For you, not the client: the Dell wasn't checking during " + ", ".join(gaps) + "."
        notify(f"📋 {p['label']} nightly status", phone, tags=["clipboard"], copy=slack)


if __name__ == "__main__":
    report() if sys.argv[1:] == ["report"] else check()
