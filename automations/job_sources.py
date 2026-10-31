"""Job fetchers. Each source returns normalized job dicts; fetch_all never lets one source kill the run."""
import datetime as dt
import html
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from common import http, load, save
from job_score import remote_location

DAYS = 3  # aggregators are newest-first; stop paging once we reach older posts
HN = "https://hacker-news.firebaseio.com/v0"
HIMALAYAS_QUERIES = ["full stack engineer", "backend engineer", "node typescript"]
_soft = []  # per-board errors from the ATS sources, so one bad slug doesn't hide the rest


def plain(h, limit=4000):
    s = html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(h or "")))  # Greenhouse double-escapes its HTML
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()[:limit]


def iso(t):
    """Unix seconds/ms, or a naive ISO string (taken as UTC), to ISO with offset."""
    if t is None or t == "":
        return None
    if isinstance(t, str):
        d = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).isoformat()
    return dt.datetime.fromtimestamp(t / 1000 if t > 1e11 else t, dt.timezone.utc).isoformat()


def fresh(posted):
    return not posted or dt.datetime.fromisoformat(posted) > dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=DAYS)


def anywhere(loc):
    """Free-text region -> True (worldwide / remote in your region, see job_score.HOME), False (restricted elsewhere), None (empty)."""
    s = (loc or "").strip()
    return remote_location(s) or bool(re.search(r"world wide|any country", s, re.I)) if s else None


def job(source, id, title, company, url, location="", remote=None, anywhere=None, visa=None, salary=(None, None, None, None),
        posted=None, text=""):
    lo, hi, cur, per = salary
    return {"id": f"{source}:{id}", "source": source, "title": (title or "").strip(), "company": (company or "").strip(),
            "url": url, "location": location, "remote": remote, "remote_anywhere": anywhere, "visa": visa,
            "salary_min": lo, "salary_max": hi, "currency": cur, "salary_period": per, "posted": posted,
            "text": plain(text)}


def get(url):
    status, text = http(url, timeout=30)
    if status != 200:
        raise RuntimeError(f"HTTP {status}" if status else text[:80])
    return text


def get_json(url):
    return json.loads(get(url))


def periods(s):
    s = (s or "").lower()
    return "year" if re.search(r"year|annual", s) else "month" if "month" in s else "hour" if "hour" in s else None


def himalayas(jc):
    out = {}
    for q in HIMALAYAS_QUERIES:
        for page in range(1, 4):
            jobs = get_json("https://himalayas.app/jobs/api/search?" + urllib.parse.urlencode(
                {"q": q, "sort": "recent", "page": page}))["jobs"]
            for j in jobs:
                posted = iso(j.get("pubDate"))
                if not fresh(posted):
                    continue
                locs, tz = j.get("locationRestrictions") or [], j.get("timezoneRestrictions") or []
                # no country list = worldwide unless the timezone list rules out UTC+6
                ok = any(anywhere(l) for l in locs) if locs else (6 in tz if tz else True)
                out[j["guid"]] = job("himalayas", j["guid"].split("/companies/")[-1], j["title"], j["companyName"], j["applicationLink"],
                                     ", ".join(locs) or "Worldwide", True, ok, None,
                                     (j.get("minSalary"), j.get("maxSalary"), j.get("currency"), periods(j.get("salaryPeriod")) if j.get("minSalary") or j.get("maxSalary") else None),
                                     posted, j.get("description") or j.get("excerpt"))
            if not jobs or not fresh(iso(jobs[-1].get("pubDate"))):
                break
            time.sleep(0.5)
    return list(out.values())


def arbeitnow(jc):
    out = []
    for page in range(1, 4):
        data = get_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")["data"]
        for j in data:
            posted = iso(j.get("created_at"))
            if fresh(posted):  # visa_sponsorship is read if the API ever sends it; it doesn't today
                out.append(job("arbeitnow", j["slug"], j["title"], j["company_name"], j["url"], j.get("location", ""),
                               j.get("remote"), None, j.get("visa_sponsorship"), posted=posted, text=j.get("description")))
        if not data or not fresh(iso(data[-1].get("created_at"))):
            break
        time.sleep(0.5)
    return out


def money(s):
    """'$50k - $70k', '60,000-80,000 EUR' -> (min, max, currency) or Nones."""
    n = [float(a.replace(",", "")) * (1000 if k else 1) for a, k in re.findall(r"(\d[\d,.]*)\s*(k)?\b", s or "", re.I)]
    n = [x for x in n if x >= (10 if "hour" in (s or "").lower() else 1000)]
    if "task" in (s or "").lower():
        n = []
    cur = "EUR" if "€" in s or "eur" in s.lower() else "GBP" if "£" in s or "gbp" in s.lower() else "USD" if "$" in s or "usd" in s.lower() else None
    return (int(min(n)), int(max(n)), cur) if n and cur else (None, None, None)


def remotive(jc):
    out = []
    for j in get_json("https://remotive.com/api/remote-jobs?category=software-dev")["jobs"]:
        posted = iso(j.get("publication_date"))
        lo, hi, cur = money(j.get("salary"))
        # only ~12 listings in total, so no freshness filter; salary is free text, yearly unless it says hour/month
        out.append(job("remotive", j["id"], j["title"], j["company_name"], j["url"], j.get("candidate_required_location", ""),
                       True, anywhere(j.get("candidate_required_location")), None,
                       (lo, hi, cur, (periods(j.get("salary")) or "year") if lo else None), posted, j.get("description")))
    return out


def wwr(jc):
    out = {}
    for cat in ("remote-full-stack-programming-jobs", "remote-back-end-programming-jobs"):
        for it in ET.fromstring(get(f"https://weworkremotely.com/categories/{cat}.rss")).iter("item"):
            f = lambda tag: (it.findtext(tag) or "").strip()
            posted = iso(dt.datetime.strptime(f("pubDate"), "%a, %d %b %Y %H:%M:%S %z").isoformat()) if f("pubDate") else None
            company, _, title = f("title").partition(": ")
            loc = ", ".join(x for x in (f("region"), f("country")) if x)
            if fresh(posted):
                out[f("guid") or f("link")] = job("wwr", f("guid") or f("link"), title or company, company if title else "",
                                                  f("link"), loc, True, anywhere(f("region")), None, posted=posted,
                                                  text=f("description"))
        time.sleep(0.5)
    return list(out.values())


def hn(jc):
    subs = get_json(f"{HN}/user/whoishiring.json")["submitted"][:6]
    thread = next(t for t in (get_json(f"{HN}/item/{i}.json") for i in subs) if t["title"].startswith("Ask HN: Who is hiring"))
    cache = load("jobs_hn.json", {})
    seen = set(cache["seen"]) if cache.get("thread") == thread["id"] else set()
    new = [k for k in thread.get("kids", []) if k not in seen]
    def item(k):
        try:
            return get_json(f"{HN}/item/{k}.json")
        except Exception:
            return None  # not marked seen below, so the next run retries it
    with ThreadPoolExecutor(16) as ex:
        items = list(ex.map(item, new))
    out = []
    for c in items:
        if c is None or c.get("deleted") or c.get("dead") or not c.get("text"):
            continue
        head = plain(c["text"].replace("<p>", "\n", 1).split("\n")[0], 300)  # "Company | Role | Location | REMOTE | VISA"
        parts = [p.strip() for p in head.split("|")]
        out.append(job("hn", c["id"], parts[1] if len(parts) > 1 else head, parts[0], f"https://news.ycombinator.com/item?id={c['id']}",
                       head, True if "remote" in head.lower() else None, posted=iso(c["time"]), text=c["text"]))
    save("jobs_hn.json", {"thread": thread["id"], "seen": sorted(seen | {k for k, c in zip(new, items) if c})})  # ponytail: marked seen before downstream scoring
    return out


def boards(source, tokens, fetch):
    out = []
    for t in tokens:
        try:
            out += fetch(t)
        except Exception as e:
            _soft.append(f"{source}/{t}: {e}")
        time.sleep(0.5)
    return out


def greenhouse(jc):
    def one(t):
        return [job("greenhouse", j["id"], j["title"], j.get("company_name") or t, j["absolute_url"], (j.get("location") or {}).get("name", ""),
                    True if "remote" in (j.get("location") or {}).get("name", "").lower() else None,
                    True if anywhere((j.get("location") or {}).get("name")) else None,
                    posted=iso(j.get("first_published")), text=j.get("content"))
                for j in get_json(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true")["jobs"]]
    return boards("greenhouse", jc.get("greenhouse", []), one)


def lever(jc):
    def one(t):
        out = []
        for j in get_json(f"https://api.lever.co/v0/postings/{t}?mode=json"):
            loc, sr = j["categories"].get("location") or "", j.get("salaryRange") or {}
            out.append(job("lever", j["id"], j["text"], t, j["hostedUrl"], ", ".join(j["categories"].get("allLocations") or [loc]),
                           True if j.get("workplaceType") == "remote" else None, True if anywhere(loc) else None,
                           salary=(sr.get("min"), sr.get("max"), sr.get("currency"), periods(sr.get("interval"))) if sr else (None,) * 4,
                           posted=iso(j.get("createdAt")), text=j.get("descriptionPlain")))
        return out
    return boards("lever", jc.get("lever", []), one)


def ashby(jc):
    def one(t):
        out = []
        for j in get_json(f"https://api.ashbyhq.com/posting-api/job-board/{t}?includeCompensation=true")["jobs"]:
            if not j.get("isListed", True):
                continue
            sal = next((c for c in (j.get("compensation") or {}).get("summaryComponents", []) if c["compensationType"] == "Salary"), {})
            locs = [j.get("location")] + [s["location"] for s in j.get("secondaryLocations") or []]
            out.append(job("ashby", j["id"], j["title"], t, j["jobUrl"], ", ".join(x for x in locs if x),
                           True if j.get("isRemote") or j.get("workplaceType") == "Remote" else None,
                           True if any(anywhere(x) for x in locs if x) else None,
                           salary=(sal.get("minValue"), sal.get("maxValue"), sal.get("currencyCode"), periods(sal.get("interval"))),
                           posted=iso(j.get("publishedAt")), text=j.get("descriptionPlain")))
        return out
    return boards("ashby", jc.get("ashby", []), one)


SOURCES = {"himalayas": himalayas, "arbeitnow": arbeitnow, "remotive": remotive, "wwr": wwr, "hn": hn,
           "greenhouse": greenhouse, "lever": lever, "ashby": ashby}


def fetch_all(jc):
    jobs, errors = [], []
    _soft.clear()
    for name in jc.get("sources", SOURCES):
        try:
            jobs += SOURCES[name](jc)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
    return jobs, errors + _soft


if __name__ == "__main__":
    demo = {"greenhouse": ["gitlab"], "lever": ["spotify"], "ashby": ["ramp"]}
    for name, fn in SOURCES.items():
        try:
            jobs = fn(demo)
            print(f"{name}: {len(jobs)}")
            if jobs:
                print("  ", {k: (v[:80] if isinstance(v, str) else v) for k, v in jobs[0].items()})
        except Exception as e:
            print(f"{name}: ERROR {type(e).__name__}: {e}")
    print("soft errors:", _soft)
