"""Run: python3 automations/test_jobs.py  (no config, network or LLM needed)"""
import json

import job_score
from job_score import DEFAULTS, hard_filter, lanes, score, usd_year

JC = {**DEFAULTS, "exclude_companies": ["BadCo"]}


def job(**kw):
    return {"title": "Senior Full-Stack Engineer", "company": "Acme", "location": "", "remote": None,
            "remote_anywhere": None, "visa": None, "salary_min": None, "salary_max": None, "currency": None,
            "salary_period": None, "text": "", **kw}


# usd_year
assert usd_year(job(salary_min=40000, salary_max=60000, currency="USD", salary_period="year")) == 50000
assert usd_year(job(salary_min=5000, currency="USD", salary_period="month")) == 60000
assert usd_year(job(salary_max=50, currency="usd", salary_period="hour")) == 104000
assert usd_year(job(salary_min=100000, currency="EUR", salary_period="year")) == 108000
assert usd_year(job(salary_min=100000, currency="XXX", salary_period="year")) is None
assert usd_year(job(salary_min=100000, currency="USD")) is None
assert usd_year(job()) is None

# lanes: remote
assert lanes(job(location="Remote - Worldwide"), JC)["remote_ok"]
assert lanes(job(text="Work from APAC timezones, UTC+6 overlap"), JC)["remote_ok"]
assert not lanes(job(location="Remote", text="US only"), JC)["remote_ok"]
assert not lanes(job(location="Remote (North America)"), JC)["remote_ok"]
assert not lanes(job(text="Must be based in the EU. Anywhere in Europe."), JC)["remote_ok"]
assert not lanes(job(location="Remote"), JC)["remote_ok"]                       # no signal
assert not lanes(job(location="Berlin", remote=False, text="worldwide team"), JC)["remote_ok"]
assert lanes(job(remote_anywhere=True, location="Remote", text="US only"), JC)["remote_ok"]  # structured wins
assert not lanes(job(remote_anywhere=False, location="Worldwide"), JC)["remote_ok"]

# lanes: visa and country
assert lanes(job(text="We offer visa sponsorship and relocation."), JC)["visa"]
assert lanes(job(text="Relocation assistance provided"), JC)["visa"]
assert not lanes(job(text="No visa sponsorship available."), JC)["visa"]       # negation beats positive
assert not lanes(job(text="We are unable to sponsor visas. Visa sponsorship is not possible"), JC)["visa"]
assert not lanes(job(text="Must have the right to work in Germany"), JC)["visa"]
assert not lanes(job(text="Great team"), JC)["visa"]
assert lanes(job(visa=True, text="no visa sponsorship"), JC)["visa"]            # structured wins
assert lanes(job(location="Amsterdam, Netherlands"), JC)["country"] == "NL"
assert lanes(job(location="Tokyo"), JC)["country"] == "JP"
assert lanes(job(location="Dubai, UAE"), JC)["country"] == "AE"
assert lanes(job(location="Berlin or Remote"), JC)["country"] == "DE"
assert lanes(job(location="London, UK"), JC)["country"] is None
assert lanes(job(location="Paris"), {**JC, "countries": ["NL"]})["country"] is None

# hard_filter
remote = dict(location="Remote - Worldwide")
assert hard_filter(job(**remote), JC) is None
assert hard_filter(job(company="badco", **remote), JC) == "excluded company"
assert hard_filter(job(title="Account Executive", **remote), JC)
assert hard_filter(job(title="Junior Full-Stack Engineer", **remote), JC)
assert hard_filter(job(title="Staff Software Engineer", **remote), JC)
assert hard_filter(job(title="Java Backend Engineer", **remote), JC)
assert hard_filter(job(title="Backend Engineer (Java)", **remote), JC)
assert hard_filter(job(title="JavaScript Software Engineer", **remote), JC) is None  # java != javascript
assert hard_filter(job(title="Software Engineer, Staffing Platform", **remote), JC) is None  # staff != staffing
assert hard_filter(job(title="Engineering Manager, Backend", **remote), JC)
assert hard_filter(job(location="New York", remote=False), JC)                  # no lane
assert hard_filter(job(location="Berlin", text="We offer visa sponsorship"), JC) is None  # lane B
assert hard_filter(job(location="London", text="We offer visa sponsorship"), JC)  # visa but non-target
assert hard_filter(job(location="Berlin", text="no visa sponsorship"), JC)
low = dict(salary_min=1000, currency="USD", salary_period="month", **remote)    # 12k/yr
assert hard_filter(job(**low), JC) == "pay $12000 below floor"
assert hard_filter(job(salary_min=2000, currency="USD", salary_period="month", **remote), JC) is None  # 24k
assert hard_filter(job(**remote), JC) is None                                    # unknown pay is kept

# score: boosts and bad LLM output
def fake(reply):
    job_score.llm = lambda *a, **k: reply


rich = job(salary_min=60000, currency="USD", salary_period="year", **remote)
fake(json.dumps({"fit": 7, "why": "good stack", "gap": ""}))
r = score(rich, JC)
assert (r["score"], r["fit"], r["why"], r["usd_year"], r["remote_ok"]) == (9, 7, "good stack", 60000, True)
assert score(job(salary_min=35000, currency="USD", salary_period="year", **remote), JC)["score"] == 8  # +1
assert score(job(**remote), JC)["score"] == 7                                    # unknown pay, no boost
b = score(job(location="Berlin, Germany", text="visa sponsorship"), JC)
assert b["score"] == 8 and b["country"] == "DE" and b["visa"]                    # lane B +1
fake(json.dumps({"fit": 10}))
assert score(rich, JC)["score"] == 10                                            # capped
for junk in ["not json", "[]", '{"fit": "high"}', '{"why": "x"}', "null", '{"fit": 99}']:
    fake(junk)
    r = score(job(**remote), JC)
    assert r["fit"] == (10 if "99" in junk else 5), junk
# office in a region vs remote in a region; marketplaces and AI-task gigs
assert not lanes(job(location="Bengaluru, Karnataka, India, APAC"), JC)["remote_ok"]
assert lanes(job(location="Home Based - APAC; Home based - EMEA"), JC)["remote_ok"]
assert lanes(job(location="Remote, Global"), JC)["remote_ok"]
assert lanes(job(location="Global"), JC)["remote_ok"]
assert hard_filter(job(location="Worldwide", company="Lemon.io"), JC) == "excluded company"
assert hard_filter(job(location="Worldwide", title="Software Engineer, AI Coding Tasks"), JC) == "title excluded"
print("ok")
