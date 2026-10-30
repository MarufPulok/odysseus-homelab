"""Copy Meeting Notes preset replies into Odysseus Notes: one note per chat, updated as the chat grows."""
import subprocess

from common import CONTAINER, cfg

# Runs inside the Odysseus container: Notes has no token API, so we use its own DB models.
INSIDE = r'''
import datetime as dt, uuid
from core.database import SessionLocal, Note, ChatMessage, Session
db = SessionLocal()
try:
    since = dt.datetime.utcnow() - dt.timedelta(days=2)
    latest = {}
    for m in (db.query(ChatMessage).filter(ChatMessage.role == "assistant", ChatMessage.timestamp >= since)
              .order_by(ChatMessage.timestamp)):
        if (m.content or "").lstrip().startswith("**Meeting:**"):
            latest[m.session_id] = m  # last one wins: the preset re-sends the full template on every update
    for sid, m in latest.items():
        s = db.get(Session, sid)
        text = m.content.strip()
        title = text.splitlines()[0].replace("**Meeting:**", "").strip()[:120] or "Meeting"
        note = db.query(Note).filter(Note.session_id == sid, Note.label == "Meeting").first()
        if note is None:
            note = Note(id=str(uuid.uuid4()), owner=s.owner if s else None, label="Meeting", source="agent",
                        session_id=sid, note_type="note", repeat="none")
            db.add(note)
        elif note.content == text:
            continue
        note.title, note.content = title, text
        print("saved:", title)
    db.commit()
finally:
    db.close()
'''


def main():
    r = subprocess.run(["docker", "exec", "-i", "-w", "/app", cfg().get("odysseus_container", CONTAINER), "python", "-"],
                       input=INSIDE, capture_output=True, text=True, timeout=120)
    out = [line for line in r.stdout.splitlines() if line.startswith("saved:")]
    print("\n".join(out) or "nothing new")
    if r.returncode:
        raise SystemExit(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"exit {r.returncode}")


if __name__ == "__main__":
    main()
