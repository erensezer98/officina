#!/bin/bash
# Attach to the coordinator's tmux session; create it if missing (resumes its last conversation when config.json knows it).
# Used by Officina's terminal panel (ttyd on port 7681) and by Terminal.app.
. "$(dirname "$0")/_env.sh"
S="$COORD_SLUG"
CONVO=$(python3 -c 'import json,os,sys;p=json.load(open(os.path.join(sys.argv[1],"config.json"))).get("coordinator_transcript","");print(os.path.basename(p).split(".")[0])' "$OFFICINA_HOME" 2>/dev/null)
ROLE="$OFFICINA_HOME/roles/$S.md"
if ! tmux has-session -t "$S" 2>/dev/null; then
  if [ -n "$CONVO" ]; then CMD="claude --resume $CONVO"; else CMD="claude -n '$COORD'"; [ -f "$ROLE" ] && CMD="$CMD --append-system-prompt-file '$ROLE'"; fi
  tmux new-session -d -s "$S" -x 160 -y 48 -c "$HOME" "$CMD; exec \$SHELL -l"
fi
exec tmux attach -t "$S"
