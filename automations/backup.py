"""Keep Odysseus safe.

  backup.py          nightly: copy Odysseus data to ~/backups/odysseus/<date>.tar.gz, keep the newest KEEP
  backup.py guard    every 5 min: when the container was recreated (update), re-apply the local patch and tell me

Timeshift skips /home, so without this nothing backs up ~/odysseus/data.
"""
import pathlib
import sqlite3
import subprocess
import sys
import tarfile
import tempfile

from common import CONTAINER as DEFAULT_CONTAINER, HOME, cfg, load, notify, now, save

ODY = pathlib.Path(cfg().get("odysseus_dir", "~/odysseus")).expanduser()
DEST = pathlib.Path.home() / "backups/odysseus"
KEEP = 14
CONTAINER = cfg().get("odysseus_container", DEFAULT_CONTAINER)
DBS = ["app.db", "scheduled_emails.db"]
# Rebuildable caches, logs and my patch leftovers; everything else in data/ is kept.
SKIP = {"fastembed_cache", "huggingface", "cache", "emoji_cache", "logs"}


def skip(name):
    """`name` is the path inside the tar ("data/app.db", "data/logs/x"). Live DBs go in via the online backup."""
    parts = name.split("/")
    if len(parts) < 2:
        return False
    base = parts[1]
    return base in SKIP or base in DBS or base.endswith((".pre-6889", ".orig", "-wal", "-shm", ".lock"))


def backup():
    DEST.mkdir(parents=True, exist_ok=True)
    DEST.chmod(0o700)  # holds the app key and integration secrets
    out = DEST / f"{now():%Y-%m-%d}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        for db in DBS:  # SQLite's online backup: consistent even while Odysseus is writing
            src = sqlite3.connect(f"file:{ODY / 'data' / db}?mode=ro", uri=True)
            dst = sqlite3.connect(f"{tmp}/{db}")
            src.backup(dst)
            ok = dst.execute("pragma integrity_check").fetchone()[0]
            src.close(), dst.close()
            if ok != "ok":
                raise RuntimeError(f"{db} backup failed integrity check: {ok}")
        part = out.with_suffix(".part")
        with tarfile.open(part, "w:gz") as tar:
            tar.add(ODY / "data", "data", filter=lambda ti: None if skip(ti.name) else ti)
            for db in DBS:
                tar.add(f"{tmp}/{db}", f"data/{db}")
            for f in (".env", "docker-compose.yml", "docker-compose.override.yml"):
                tar.add(ODY / f, f)
        part.chmod(0o600)
        part.replace(out)
    for old in sorted(DEST.glob("*.tar.gz"))[:-KEEP]:
        old.unlink()


def guard():
    cid = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", CONTAINER],
                         capture_output=True, text=True).stdout.strip()
    if not cid:
        return  # container down: the watchdog/you will notice; nothing to patch
    st = load("guard.json", {})
    if st.get("container") in (None, cid):
        save("guard.json", {"container": cid})
        return
    # Recreated (docker compose pull/up): in-container edits are gone. Re-apply the stopgap.
    r = subprocess.run([str(HOME / "patches/odysseus-skills-index.sh")], capture_output=True, text=True, timeout=180)
    msg = (r.stdout + r.stderr).strip()[-400:]
    if r.returncode == 0:
        notify("🔧 Odysseus updated", f"Container was recreated; agent-tools patch re-applied.\n`{msg}`", tags=["wrench"])
    else:
        notify("⚠️ Odysseus updated, patch failed", f"Check if PR #6889 is merged upstream.\n`{msg}`",
               priority=4, tags=["warning"])
    save("guard.json", {"container": cid})


if __name__ == "__main__":
    try:
        guard() if sys.argv[1:] == ["guard"] else backup()
    except Exception as e:
        notify("⚠️ Odysseus backup/guard failed", str(e)[:500], priority=4, tags=["warning"])
        raise
