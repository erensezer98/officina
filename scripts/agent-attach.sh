#!/bin/bash
# Officina agent tab: attach to an agent's tmux session. ttyd passes the session name as $1 (?arg=<tmux>).
. "$(dirname "$0")/_env.sh"
S="$1"
team_field tmux | grep -qx -- "$S" || { printf '\n  unknown agent: %s\n' "$S"; sleep 3600; exit 0; }
while ! tmux has-session -t "$S" 2>/dev/null; do printf '\r  %s is not running in the background yet …' "$S"; sleep 2; done
exec tmux attach -t "$S"
