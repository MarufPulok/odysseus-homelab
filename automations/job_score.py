"""Job radar scoring: salary normalisation, lane detection, hard filter, local-LLM fit score."""
import json
import re

from common import llm

DEFAULTS = {
    "title_include": [r"full[- ]?stack", r"back[- ]?end", r"front[- ]?end", r"software (engineer|developer)",
                      r"\bnode(\.?js)?\b", r"typescript", r"\breact\b", r"next\.?js", r"web developer",
                      r"platform engineer", r"product engineer"],
    "title_exclude": [r"\bintern(ship)?\b", r"\bjunior\b", r"\bprincipal\b", r"\bstaff\b", r"\bdirector\b",
                      r"head of", r"\bmanager\b", r"\bsales\b", r"\bmarketing\b", r"\bdesigner\b",
                      r"data scientist", r"\bml engineer\b", r"\bios\b", r"\bandroid\b", r"\bembedded\b",
                      r"firmware", r"\bqa\b", r"recruiter", r"\bphp\b", r"\.net\b", r"\bc#", r"\bjava\b",
                      r"\bruby\b", r"werkstudent", r"praktikum",
                      r"\bai (coding |training )?tasks?\b", r"ai trainer", r"\brlhf\b", r"annotat", r"data label"],
    "min_usd_year": 18000,  # only applied when pay is listed
    "boost_usd_year": [30000, 50000],
    "countries": ["NL", "DE", "JP", "IE", "AE", "SG"],
}

# talent marketplaces and AI-training gig shops post "jobs" that are contract pools, not roles
MARKETPLACE = re.compile(r"lemon\.io|toptal|\bturing\b|andela|crossover|braintrust|gun\.io|arc\.dev|x-team|"
                         r"mercor|outlier|dataannotation|data annotation|alignerr|micro1|remotasks", re.I)

FX = {"USD": 1, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "AUD": 0.65, "JPY": 0.0067, "SGD": 0.74,
      "AED": 0.27, "INR": 0.012, "CHF": 1.13, "PLN": 0.25, "SEK": 0.095}  # rough, for thresholds only
PERIOD = {"year": 1, "month": 12, "hour": 2080}

REMOTE_NO = re.compile(r"\bus[- ]only\b|\bus[- ]based\b|(based|located|reside|residents?) (in|of) the (us|u\.s\.|usa|eu|uk)\b|"
                       r"\b(us|eu|uk|european|canadian) (residents|citizens|timezones?)\b|north america|"
                       r"\bmust (be|live) in (the )?(us|usa|eu|uk|europe)\b|(us|usa|uk|eu|europe)[- ]only", re.I)
HOME = r"bangladesh|utc ?\+ ?6"  # where you live and your time zone; edit both (and REGION) for your location
REMOTE_YES = re.compile(rf"worldwide|anywhere|everywhere|{HOME}|any time ?zone", re.I)  # checked against the location only
REGION = re.compile(r"\bglobal(ly)?\b|\bapac\b|\basia\b", re.I)
REMOTE_WORD = re.compile(r"remote|home|distributed", re.I)
REMOTE_TEXT = re.compile(r"remote[^.]{0,40}\b(worldwide|anywhere in the world|apac|asia)\b|" + HOME, re.I)  # descriptions say "global" about everything
VISA_NO = re.compile(r"(no|not|without|unable to|cannot|can't|can not|not able to|don't|do not) "
                     r"(offer |provide |able to )?(visa )?sponsor|must have (the )?(legal )?right to work|"
                     r"must be (legally )?(authori[sz]ed|eligible) to work", re.I)
VISA_YES = re.compile(r"visa sponsorship|sponsor(s|ing)? (your |a |work )?visa|we sponsor|relocation (package|support|assistance)|"
                      r"relocation (is )?(provided|offered|available)|work permit support", re.I)
CITIES = {"NL": "netherlands|holland|amsterdam|rotterdam|utrecht|eindhoven|the hague|delft",
          "DE": "germany|deutschland|berlin|munich|münchen|hamburg|frankfurt|cologne|köln|stuttgart|düsseldorf",
          "JP": "japan|tokyo|osaka|kyoto|yokohama|fukuoka",
          "IE": "ireland|dublin|cork|galway",
          "AE": "uae|united arab emirates|dubai|abu dhabi",
          "SG": "singapore"}


def usd_year(job):
    lo, hi = job.get("salary_min"), job.get("salary_max")
    vals = [v for v in (lo, hi) if v]
    fx, per = FX.get((job.get("currency") or "").upper()), PERIOD.get(job.get("salary_period"))
    if not vals or fx is None or per is None:
        return None
    return int(sum(vals) / len(vals) * per * fx)


def remote_location(loc):
    """"Remote, APAC" or plain "Global" is remote; "Bengaluru, India, APAC" is an office in that region."""
    if REMOTE_YES.search(loc):
        return True
    rest = REGION.sub("", loc)
    return bool(REGION.search(loc) and (REMOTE_WORD.search(rest) or not re.sub(r"[\W_]", "", rest)))


def lanes(job, jc):
    loc, text = job.get("location") or "", job.get("text") or ""
    blob = f"{loc} {text}"
    ra = job.get("remote_anywhere")
    if ra is None:
        ra = (job.get("remote") is not False and not REMOTE_NO.search(blob)
              and (remote_location(loc) or bool(REMOTE_TEXT.search(text))))
    visa = job.get("visa")
    if visa is None:
        visa = not VISA_NO.search(text) and bool(VISA_YES.search(text))
    country = next((c for c in jc["countries"]  # ISO code only in capitals: "de"/"ie" are ordinary words
                    if re.search(rf"\b{c}\b", loc) or (c in CITIES and re.search(rf"\b({CITIES[c]})\b", loc, re.I))), None)
    return {"remote_ok": bool(ra), "visa": bool(visa), "country": country}


def hard_filter(job, jc):
    title, company = job.get("title") or "", (job.get("company") or "").lower()
    if company in [c.lower() for c in jc.get("exclude_companies", [])] or MARKETPLACE.search(company):
        return "excluded company"
    if not any(re.search(p, title, re.I) for p in jc["title_include"]):
        return "title not a match"
    if any(re.search(p, title, re.I) for p in jc["title_exclude"]):
        return "title excluded"
    ln = lanes(job, jc)
    if not (ln["remote_ok"] or (ln["visa"] and ln["country"])):
        return "no remote-from-home or visa lane"
    pay = usd_year(job)
    if pay is not None and pay < jc["min_usd_year"]:
        return f"pay ${pay} below floor"
    return None


SYSTEM = ("You rate how well a job fits a candidate. Be strict: most jobs score 3-6. Reply with JSON only: "
          '{"main_stack": "the job\'s main languages and frameworks, max 6 words", "fit": 0-10 integer, '
          '"why": "max 12 words", "gap": "max 10 words, or empty"}. '
          "Take main_stack from what the engineer will write every day, not from the company's product or nice-to-haves. "
          "Caps: main language not among the candidate's strong skills -> fit at most 5. Infrastructure, kernel, "
          "networking, storage, SRE, database-internals or ML research role -> at most 5 unless the candidate's profile "
          "lists that kind of work. Asks for far more years or a higher level than the candidate -> at most 6. "
          "Scale: 9-10 = same main language, same role type, seniority fits. 7-8 = same main language, related role "
          "type (e.g. frontend-only for a full-stack candidate). 4-6 = partial overlap. 0-3 = different field. "
          "Ignore location and pay; they are scored elsewhere.")


def score(job, jc):
    ln, pay = lanes(job, jc), usd_year(job)
    prompt = (f"Candidate:\n{jc.get('profile', '')}\n\nJob: {job.get('title')} at {job.get('company')}\n"
              f"Location: {job.get('location')}\nPay: {f'~${pay}/yr' if pay else 'unknown'}\n"
              f"{(job.get('text') or '')[:2500]}")
    try:  # a down Ollama raises RuntimeError on purpose: the caller should retry, not mark the job seen
        j = json.loads(llm(prompt, SYSTEM, fmt="json", max_tokens=150))
        fit = max(0, min(10, int(float(j["fit"]))))
        why, gap = str(j.get("why") or "")[:120], str(j.get("gap") or "")[:100]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        fit, why, gap = 5, "", ""
    boost = 1 if ln["visa"] and ln["country"] else 0
    if ln["remote_ok"] and pay:
        b1, b2 = jc["boost_usd_year"]
        boost += 2 if pay >= b2 else 1 if pay >= b1 else 0
    return {"score": min(10, fit + boost), "fit": fit, "why": why, "gap": gap, "usd_year": pay, **ln}
