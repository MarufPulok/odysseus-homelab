#!/usr/bin/env bash
# Re-apply after an Odysseus update (docker compose pull/up recreates the container and drops this edit).
# Bug: the "available skills index" context arms the external-context tool gate, so every agent
# chat is blocked from calendar/notes reads ("external untrusted context blocks read_private").
set -euo pipefail
C=${ODYSSEUS_CONTAINER:-odysseus-odysseus-1}
docker exec -i -w /app "$C" python - <<"PY"
p = "src/chat_processor.py"; s = open(p).read()
if "\"available skills index\",\n                    \"\\n\".join(lines),\n                    # Server-owned" in s:
    print("already patched"); raise SystemExit
old = "\"available skills index\",\n                    \"\\n\".join(lines),\n                ))"
if s.count(old) != 1:
    raise SystemExit("code changed upstream; check if the bug is fixed before patching")
s = s.replace(old, "\"available skills index\",\n                    \"\\n\".join(lines),\n                    # Server-owned skill names, like the agent loop \"skills\" block: do not taint the run.\n                    arm_tool_gate=False,\n                ))")
open(p, "w").write(s); print("patched")
PY
docker restart "$C" >/dev/null && echo restarted
