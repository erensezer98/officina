#!/bin/bash
# Move a running agent from its Terminal.app window into a background tmux session (same conversation).
# Usage: move-agent.sh "<Agent name>"     (then close the old Terminal window)
. "$(dirname "$0")/_env.sh"
NAME="$1"; [ -z "$NAME" ] && { echo "usage: move-agent.sh \"<Agent name>\""; exit 1; }
SLUG=$(echo "$NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-|-$//g')
F=$(grep -l "\"name\":\"$NAME\"" "$HOME"/.claude/sessions/*.json 2>/dev/null | while read -r f; do p=$(basename "$f" .json); kill -0 "$p" 2>/dev/null && echo "$f"; done | head -1)
[ -z "$F" ] && { echo "no live session named $NAME"; exit 1; }
PID=$(basename "$F" .json); SID=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sessionId"])' "$F")
tmux has-session -t "$SLUG" 2>/dev/null && { echo "tmux session $SLUG already exists"; exit 1; }
echo "$NAME: pid $PID, conversation $SID -> tmux $SLUG"
kill "$PID"; sleep 3
OV="$OFFICINA_HOME/agents/$SLUG.settings.json"; X=""; [ -s "$OV" ] && X="--settings $OV"   # per-agent overrides (profile page)
tmux new-session -d -s "$SLUG" -x 160 -y 48 -c "$HOME" "claude --resume $SID $X; exec \$SHELL -l"
sleep 6; tmux capture-pane -p -t "$SLUG" | grep -v '^\s*$' | tail -6
echo "moved: $NAME is now in tmux session '$SLUG' (Officina tab)."
