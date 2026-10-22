#!/usr/bin/env python3
"""Every 10 min: remember which agent runs in which tmux session and which conversation (sessionId).
Writes <office>/team.json; team-autostart.sh uses it after a restart."""
import json, os, glob, time
H = os.path.expanduser("~"); O = os.environ.get("OFFICINA_HOME") or f"{H}/.claude/office"; out = {}
for f in glob.glob(f"{H}/.claude/sessions/*.json"):
    try:
        d = json.load(open(f)); os.kill(int(d["pid"]), 0)
    except Exception:
        continue
    tm = (d.get("tmux") or "").split(":")[0]; name = d.get("name") or ""
    if tm and name:
        out[tm] = {"name": name, "sessionId": d["sessionId"], "cwd": d.get("cwd", H), "seen": time.strftime("%Y-%m-%d %H:%M")}
p = f"{O}/team.json"
old = json.load(open(p)) if os.path.exists(p) else {}
old.update(out)                       # keep agents that are briefly down
json.dump(old, open(p + ".tmp", "w"), indent=1); os.replace(p + ".tmp", p)
