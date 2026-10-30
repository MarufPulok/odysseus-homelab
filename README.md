# odysseus-homelab

Turn an old laptop into an always-on personal assistant built around
[Odysseus](https://github.com/odysseus-dev/odysseus) (self-hosted AI workspace).
Small Python jobs run on systemd timers, use a local model for anything private,
and push results to your phone with [ntfy](https://ntfy.sh).

Nothing here is tied to one job or company. Every job is one file, every personal
value lives in `config.toml`, and adding your own job takes about 20 lines.

```
 phone (ntfy app) <──── ntfy ◄─────────────┐
        │                                  │ notify()
        └─ Tailscale ─► Odysseus (Docker) ◄┤ odysseus()      automations/*.py
                          │                │ llm()           on systemd timers
                          └─► Ollama ◄─────┘
                              (local model, free, private)
```

Tested on a Dell Inspiron 3505 (Ryzen 5 3500U, 16 GB, no dGPU) running Manjaro.
A 4B model runs at about 8 tokens/s on the iGPU, which is enough for background jobs.

## What's in here

| Path | What it is |
|---|---|
| `setup/` | Root setup for Arch/Manjaro: Docker, Ollama, Tailscale, ufw, btrfs snapshots. `UPDATING.md` is the update routine. |
| `odysseus/` | Compose override for the Odysseus clone (fixed bridge name so ufw can allow Ollama). |
| `automations/common.py` | Shared helpers every job uses: `cfg()`, `notify()`, `llm()`, `odysseus()`, `load()`/`save()`, `todo_from_text()`. |
| `automations/*.py` | The jobs (table below). |
| `automations/install-timers.sh` | Writes and enables the systemd user timers. Safe to re-run. |
| `automations/skills/` | Two Odysseus skills: client message rephraser, meeting-notes template. |
| `automations/patches/` | Stopgap patch for an Odysseus agent-tools bug (upstream fix: PR #6889). |

## Jobs

Pick the ones you want. Each needs only the config section named here.

| Job | Schedule | What it does | Needs |
|---|---|---|---|
| `watchdog.py` | every 5 min | Checks your sites; alerts on 2 failures in a row and on recovery. `report` mode sends a paste-ready nightly status for a client. | `[[project]]` |
| `brief.py` | daily | Morning brief: calendar, deadlines, site status, 2-line focus from the local model. | Odysseus token |
| `prep.py` | every 10 min | 10-20 min before a meeting that names a project, pushes that project's open tasks. Also pulls CalDAV. | Odysseus token, `[[project]]` |
| `capture.py` | service | Text sent from your phone to an ntfy topic becomes a todo with a reminder; a link becomes a summary document. | `[capture]`, Odysseus token |
| `releases.py` | weekly | Digest of new stable releases of the repos you follow. | `[releases]` |
| `backup.py` | nightly | Consistent SQLite backup of Odysseus data, keeps 14. `guard` mode re-applies the patch after an Odysseus update. | Docker |
| `meeting_notes.py` | every 5 min | Copies "Meeting Notes" chat replies into Odysseus Notes. | Docker |
| `weekly.py` | Friday | Weekly status update for your lead from your tasks. | `notion_sync.py` |
| `slack_todos.py` | every 15 min | Slack DMs and mentions outside work hours become todos (title + link only). | `[slack_todos]`, Slack session |
| `vulns.py` | every 2 h | Posts high/critical Node.js and npm advisories for your packages to a Slack channel. | `[vulns]`, Slack session |
| `notion_sync.py` | 5x daily | Mirrors tasks assigned to you on a Notion board into the Odysseus calendar. | `[notion]`, browser login |

**Slack and Notion jobs are optional examples.** They act as you through your own
browser session (Slack: the `xoxc` token and `d` cookie, Notion: a logged-in Chrome
profile over CDP), because they were built for workspaces where the user is a guest
and can't install an app. Check your workspace's rules first. If you can create a
Slack app or Notion integration, swap `common.slack()` or `cdp.notion_api()` for the
official API.

## Setup

1. **Base system** (Arch/Manjaro; read the script first, it resets ufw):
   ```bash
   sudo bash setup/setup-root.sh          # optional: sudo NEW_HOSTNAME=homelab bash ...
   sudo bash setup/ollama-vulkan.sh on    # only for AMD iGPU acceleration
   ollama pull qwen3:4b-instruct-2507-q4_K_M   # with OLLAMA_HOST=172.17.0.1:11434
   ```
2. **Odysseus**: clone it to `~/odysseus`, copy `odysseus/docker-compose.override.yml`
   next to its compose file, then set these in its `.env`:
   ```bash
   OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
   APP_BIND=127.0.0.1
   APP_PORT=7011
   ALLOWED_ORIGINS=https://<machine>.<tailnet>.ts.net,http://localhost:7011
   OAUTH_REDIRECT_BASE_URL=https://<machine>.<tailnet>.ts.net
   NTFY_BASE_URL=https://<machine>.<tailnet>.ts.net:8443
   SECURE_COOKIES=true
   ```
   `docker compose up -d`, then `sudo bash setup/tailscale-serve.sh` to reach it from your
   tailnet only (nothing is exposed to the internet).
3. **Token**: in Odysseus, Settings > Integrations > add a Claude Agent, toggle the
   calendar, todos and documents scopes, and save the token:
   ```bash
   mkdir -p ~/.config/automations && umask 077
   echo 'ody_...' > ~/.config/automations/odysseus-token
   ```
4. **Automations**: clone this repo, then
   ```bash
   cp automations/config.example.toml automations/config.toml   # edit it
   ln -s "$PWD/automations" ~/automations                        # the timers run from here
   ~/automations/install-timers.sh auto-watchdog auto-brief auto-capture   # or no args for all
   ```
   Subscribe to your `ntfy_topic` in the ntfy phone app via the Tailscale URL.
   Jobs that need the Notion browser login run from `automations/.venv`
   (`python3 -m venv .venv && .venv/bin/pip install websockets`).

Python 3.11+ (for `tomllib`). No other dependencies.

## Add your own job

A job is a script that imports from `common.py`. Example: ping your phone when a
GitHub repo gets a new issue.

```python
# automations/issues.py
"""New issues on [issues].repo → phone."""
import json

from common import cfg, http, load, notify, save


def main():
    repo = cfg()["issues"]["repo"]
    status, text = http(f"https://api.github.com/repos/{repo}/issues?state=open&per_page=20")
    if status != 200:
        raise RuntimeError(f"GitHub: HTTP {status}")
    seen = set(load("issues.json", []))
    for i in json.loads(text):
        if i["id"] not in seen and "pull_request" not in i:
            notify(f"New issue in {repo}", f"[{i['title']}]({i['html_url']})", tags=["bug"])
            seen.add(i["id"])
    save("issues.json", sorted(seen))


if __name__ == "__main__":
    main()
```

Then add `[issues]` with `repo = "owner/name"` to `config.toml`, add one line to the
`jobs` list in `install-timers.sh`, and install it:

```bash
"auto-issues|*:0/30|issues.py|false"      # name | OnCalendar | command | catch up if missed
~/automations/install-timers.sh auto-issues
```

Helpers you get for free:

- `notify(title, markdown, priority, tags, click, copy)` sends to your phone. `copy` adds a copy-to-clipboard button.
- `llm(prompt, system, fmt="json")` calls the local model. Use it for anything private.
- `odysseus("/todos", {...})` calls the scoped Odysseus API (todos, calendar, documents).
- `todo_from_text(text)` turns free text into `{action, title, due}` with a correct time zone.
- `load(name, default)` / `save(name, data)` store job state as JSON in `automations/state/`.

Logs: `journalctl --user -u auto-issues`.

## Privacy

- Scheduled jobs use the local model only. Message text from Slack never leaves the machine.
- `slack_todos.py` keeps titles free of names and personal details, with a prompt rule
  plus a regex for titled names. Bare names still rely on the prompt.
- Odysseus, ntfy and SSH are reachable over Tailscale only. ufw blocks everything else.

## License

MIT
