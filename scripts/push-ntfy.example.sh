#!/bin/bash
# OPTIONAL phone push via ntfy (https://ntfy.sh). Usage: push-ntfy.sh "Title" "Text" [url]
# Put your own secret topic in ~/.config/officina/ntfy-topic (one line, never commit it), then set
# "push_script": "<path to this file>" in config.json and "push": true in <office>/flow/config.json.
T=$(cat "$HOME/.config/officina/ntfy-topic" 2>/dev/null); [ -z "$T" ] && exit 0
args=(-s -m 15 -H "Title: $1")
[ -n "$3" ] && args+=(-H "Click: $3")
curl "${args[@]}" -d "$2" "https://ntfy.sh/$T" >/dev/null
