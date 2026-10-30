"""Security alerts to the team Slack channel: high/critical Node.js security releases and high/critical npm advisories
for our stack. One line + official link per package, nothing else.

  vulns.py          check sources, post anything new as ONE message to [vulns].slack_channel (silent when nothing new)
  vulns.py seed     mark everything published so far as seen, post nothing (first install)
  vulns.py test     DM yourself the latest Node bulletin + the busiest advisory day, as one post

Posts as you, with your Slack browser session saved in ~/.config/automations/slack-session.json (mode 600).
"""
import datetime as dt
import json
import re
import sys
import urllib.parse
import urllib.request

from common import SLACK_SESSION, cfg, http, load, notify, save, slack

NODE_INDEX = "https://nodejs.org/dist/index.json"
GHSA = "https://api.github.com/advisories"


def esc(s):
    """Slack mrkdwn escaping: dynamic text can never become a link or an @channel ping."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def node_releases():
    """{"YYYY-MM": [versions]}: one entry per monthly bulletin (release lines can ship a day apart)."""
    status, text = http(NODE_INDEX, timeout=30)
    if status != 200:
        raise RuntimeError(f"nodejs.org index: HTTP {status}")
    days = {}
    for r in json.loads(text):
        if r["security"]:
            days.setdefault(r["date"][:7], []).append(r["version"].lstrip("v"))
    return days


def node_message(month, versions):
    """None unless the bulletin has a high or critical issue."""
    d = dt.date.fromisoformat(month + "-01")
    link = f"https://nodejs.org/en/blog/vulnerability/{d:%B}-{d.year}-security-releases".lower()
    status, page = http(link, timeout=30)
    if status != 200:
        raise RuntimeError(f"Node bulletin not found at {link}: HTTP {status}")
    sev = "critical" if re.search(r"\(critical\)", page, re.I) else "high" if re.search(r"\(high\)", page, re.I) else None
    if not sev:
        return None
    vs = " / ".join(f"*{v}*" for v in sorted(versions, key=lambda v: [int(x) for x in v.split(".")]))
    return f":rotating_light: *Node.js: {sev} security issue.* Upgrade to {vs}\n{link}"


def advisories(packages):
    """High and critical npm advisories touching our packages (GitHub Advisory Database), newest first."""
    found = []
    for sev in ("critical", "high"):  # the API takes one severity per call
        status, text = http(f"{GHSA}?ecosystem=npm&severity={sev}&per_page=100&affects={','.join(packages)}",
                            headers={"Accept": "application/vnd.github+json"}, timeout=30)
        if status == 403 and "rate limit" in text:
            return None  # 60 calls/hour per IP without a token; the next run retries
        if status != 200:
            raise RuntimeError(f"GitHub advisories: HTTP {status} {text[:200]}")
        found += json.loads(text)
    return sorted(found, key=lambda a: a["published_at"], reverse=True)


def _ver(v):
    return [int(x) for x in re.findall(r"\d+", v)[:3]]


def package_items(found, packages):
    """One item per package, however many advisories it got: one action (upgrade) per line."""
    by_pkg = {}
    for a in found:
        for v in a.get("vulnerabilities") or []:
            name = (v.get("package") or {}).get("name")
            if name in packages:
                by_pkg.setdefault(name, {"ads": {}, "fixes": set()})
                by_pkg[name]["ads"][a["ghsa_id"]] = a
                if v.get("first_patched_version"):
                    by_pkg[name]["fixes"].add(v["first_patched_version"])
    items = []
    for name, p in sorted(by_pkg.items()):
        ads = list(p["ads"].values())
        latest = {}  # newest fix per major line: the version that clears every issue on that line
        for f in p["fixes"]:
            major = _ver(f)[:1]
            if str(major) not in latest or _ver(f) > _ver(latest[str(major)]):
                latest[str(major)] = f
        fixes = " / ".join(f"*{esc(f)}*" for f in sorted(latest.values(), key=_ver)) or "no fix yet"
        if len(ads) == 1:
            a = ads[0]
            ident = f" ({esc(a['cve_id'])})" if a.get("cve_id") else ""
            head, link = f"{a['severity']} security issue{ident}", a["html_url"]
        else:
            crit = sum(a["severity"] == "critical" for a in ads)
            head = f"{len(ads)} {'high ' if not crit else ''}security issues" + (f" ({crit} critical)" if crit else "")
            link = "https://github.com/advisories?query=" + urllib.parse.quote(f"ecosystem:npm affects:{name}")
        items.append(f":rotating_light: *{esc(name)}: {head}.* Upgrade to {fixes}\n{link}")
    return items


def slack_post(channel, text):
    if channel == "me":
        channel = json.loads(SLACK_SESSION.read_text())["teams"][0]["user_id"]
    slack("chat.postMessage", channel=channel, text=text, unfurl_links="false", unfurl_media="false")


def main(mode):
    c = cfg()["vulns"]
    st = load("vulns.json", {"node": [], "ghsa": []})
    days = node_releases()
    found = advisories(c["packages"])
    if found is None:
        return
    if mode == "seed":
        save("vulns.json", {"node": sorted(days), "ghsa": [a["ghsa_id"] for a in found]})
        return
    if mode == "test":  # latest Node bulletin + the busiest advisory day, as one post would look
        busiest = max({a["published_at"][:10] for a in found}, key=lambda d: sum(a["published_at"][:10] == d for a in found))
        new_months, new_ads = [max(days)], [a for a in found if a["published_at"][:10] == busiest]
    else:
        new_months = sorted(set(days) - set(st["node"]))
        new_ads = [a for a in found if a["ghsa_id"] not in st["ghsa"]]
    items = [m for m in (node_message(month, days[month]) for month in new_months) if m]
    items += package_items(new_ads, set(c["packages"]))
    if items:  # one post per check, whatever it found
        slack_post("me" if mode == "test" else c["slack_channel"], "\n\n".join(items))
    if mode != "test":  # only after a successful post, so a failure retries next run
        save("vulns.json", {"node": st["node"] + new_months, "ghsa": st["ghsa"] + [a["ghsa_id"] for a in new_ads]})


if __name__ == "__main__":
    try:
        main(sys.argv[1] if sys.argv[1:] else "check")
    except Exception as e:
        notify("⚠️ Vulnerability alerts failed", str(e)[:500], priority=4, tags=["warning"])
        raise
