#!/bin/bash
# After login: start every known agent (team.json, written by team-snapshot.py) in its own tmux session,
# continuing its own conversation. Only Claude Code's "trust this folder" question may then wait for you.
. "$(dirname "$0")/_env.sh"
sleep 20                                            # let the network come up
T="$OFFICINA_HOME/team.json"; [ -f "$T" ] || exit 0
python3 -c 'import json,sys
for k,v in json.load(open(sys.argv[1])).items(): print(k, v["sessionId"], v["name"].replace(" ","_"))' "$T" | while read -r slug sid name; do
  name="${name//_/ }"
  tmux has-session -t "$slug" 2>/dev/null && continue
  extra=""; OV="$OFFICINA_HOME/agents/$slug.settings.json"; [ -s "$OV" ] && extra="--settings $OV"
  tmux new-session -d -s "$slug" -x 160 -y 48 -c "$HOME" "claude --resume $sid -n '$name' $extra; exec \$SHELL -l"
  echo "$(date '+%F %T') started $name ($slug)" >> "$OFFICINA_HOME/autostart.log"
done
