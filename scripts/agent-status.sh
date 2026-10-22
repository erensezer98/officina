#!/bin/bash
# Set one agent's line on Officina's team board.
# Usage: agent-status.sh "<Agent>" "<what it is doing>" ["<what it needs from the human>"]
# Empty 3rd arg = nothing needed. Use "idle" as 2nd arg when done.
dir="$HOME/.claude/status"; mkdir -p "$dir"
name="$1"; doing="$2"; needs="${3:-}"
{ [ -z "$name" ] || [ -z "$doing" ]; } && { echo "usage: agent-status.sh AGENT DOING [NEEDS]"; exit 1; }
f="$dir/$(echo "$name" | tr ' /' '__').txt"
printf '%s\n%s\n%s\n%s\n' "$name" "$doing" "$needs" "$(date +%H:%M)" > "$f"
