"""Weekly digest of stable releases for your stack, summarised by the local Qwen."""
import datetime as dt
import json

from common import cfg, http, llm, notify, now

MINOR = "MINOR"
SYSTEM = ("You summarise software release notes for a developer who uses these projects. "
          "Reply with at most 3 bullets starting with '- ', each under 20 words. Cover only breaking changes, "
          "deprecations, security fixes, and features worth knowing. Never write a bullet saying something is 'None'. "
          f"If nothing is notable, reply exactly: {MINOR}")


def summarise(repo, r):
    notes = (r.get("body") or "")[:5000]
    if not notes:
        return MINOR
    lines = [l.strip() for l in llm(f"Release {r['tag_name']} of {repo}:\n\n{notes}", SYSTEM, max_tokens=200).splitlines()]
    lines = [l for l in lines if l.startswith("- ") and "none" not in l.lower()[:40]]
    return "\n".join(lines) or MINOR


def main():
    since = now() - dt.timedelta(days=7)
    sections, minor = [], []
    for repo in cfg()["releases"]["repos"]:
        status, text = http(f"https://api.github.com/repos/{repo}/releases?per_page=30",
                            headers={"Accept": "application/vnd.github+json"})
        if status != 200:
            sections.append(f"**{repo}**\n- couldn't fetch (HTTP {status})")
            continue
        fresh = [r for r in json.loads(text)
                 if not r["draft"] and not r["prerelease"]
                 and dt.datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")) > since]
        name = repo.split("/")[1]
        for r in reversed(fresh):  # oldest first
            s = summarise(repo, r)
            if s == MINOR:
                minor.append(f"{name} {r['tag_name']}")
            else:
                sections.append(f"**{name} {r['tag_name']}** · [notes]({r['html_url']})\n{s}")
    if minor:
        sections.append("**Minor fixes only:** " + ", ".join(minor))
    notify("📦 Stack releases this week", "\n\n".join(sections) or "No new stable releases this week.", tags=["package"])


if __name__ == "__main__":
    main()
