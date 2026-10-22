#!/bin/bash
# Claude Code Notification / Stop hook -> one small status file per session, read by Officina's flow lanes
# ("waits for permission", "waits for input", "idle"). Reads the hook JSON on stdin. Never blocks, never prints.
# Usage in ~/.claude/settings.json: see README "Claude Code hooks". Argument: the event name (notification | stop).
EV="$1"
D="${OFFICINA_HOME:-$HOME/.claude/office}/flow/hooks"; mkdir -p "$D" 2>/dev/null
/usr/bin/python3 -c '
import json, sys, os, time
try: d = json.load(sys.stdin)
except Exception: d = {}
sid = "".join(ch for ch in str(d.get("session_id", "unknown")) if ch.isalnum() or ch == "-")[:80] or "unknown"
out = os.path.join(sys.argv[2], sid + ".json")
json.dump({"event": sys.argv[1], "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "message": d.get("message", ""), "cwd": d.get("cwd", ""),
           "transcript": d.get("transcript_path", "")}, open(out + ".tmp", "w")); os.replace(out + ".tmp", out)
' "$EV" "$D" 2>/dev/null
exit 0
