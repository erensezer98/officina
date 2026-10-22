#!/bin/bash
# Scheduler helper (LaunchAgent): type "ROUTINE <name>" into an agent's tmux session, e.g. routine.sh tech workflow-review.
# The agent's role card says what each routine means. Does nothing if the agent is not running.
. "$(dirname "$0")/_env.sh"
S="$1"; R="$2"; [ -z "$S" ] || [ -z "$R" ] && { echo "usage: routine.sh <tmux session> <routine>"; exit 1; }
tmux has-session -t "$S" 2>/dev/null || exit 0
tmux send-keys -t "$S" "ROUTINE $R" Enter
