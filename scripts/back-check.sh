#!/bin/bash
# Every 5 min: if the previous run is > 2 h old, the Mac was asleep → ask the coordinator for a short "while you were away" brief.
. "$(dirname "$0")/_env.sh"
S="$OFFICINA_HOME/.last-seen"; now=$(date +%s); last=$(cat "$S" 2>/dev/null || echo $now); echo $now > "$S"
gap=$((now-last))
if [ $gap -gt 7200 ]; then
  W="$(cfg wake_file "$OFFICINA_HOME/wake.txt")"
  printf '[back] The Mac was asleep for %d h %d min. %s: give a short brief: what the team did, what waits on the human (cards, drafts).\n' $((gap/3600)) $((gap%3600/60)) "$COORD" >> "$W"
fi
