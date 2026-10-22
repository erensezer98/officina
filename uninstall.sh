#!/bin/bash
# Remove Officina's LaunchAgents and the app. Your data folder stays unless you add --purge (asks first).
REPO="$(cd "$(dirname "$0")" && pwd)"; HOME_DIR="${OFFICINA_HOME:-$HOME/.claude/office}"
for p in "$HOME"/Library/LaunchAgents/com.officina.*.plist; do
  [ -e "$p" ] || continue
  launchctl bootout "gui/$(id -u)" "$p" 2>/dev/null; rm -f "$p"; echo "removed $(basename "$p")"
done
[ -d "$HOME/Applications/Officina.app" ] && rm -rf "$HOME/Applications/Officina.app" && echo "removed ~/Applications/Officina.app"
if [ "$1" = "--purge" ]; then
  read -r -p "Delete ALL Officina data in $HOME_DIR (cards, tasks, votes, markups, config)? Type yes: " a
  [ "$a" = yes ] && rm -rf "$HOME_DIR" && echo "deleted $HOME_DIR"
else
  echo "Data kept in $HOME_DIR (use --purge to delete it). Remove the hook lines from ~/.claude/settings.json yourself if you added them."
fi
