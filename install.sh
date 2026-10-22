#!/bin/bash
# Officina installer for macOS. Never uses sudo. Never edits your Claude Code settings. Never overwrites existing data.
#   ./install.sh                      full install (data folder, venv, LaunchAgents)
#   ./install.sh --name "Ada"         your first name, shown in the app (default: your macOS first name)
#   ./install.sh --port 4242          web port
#   ./install.sh --home DIR           data folder (default ~/.claude/office; also env OFFICINA_HOME)
#   ./install.sh --no-launchd         do not install LaunchAgents (start the server by hand)
#   ./install.sh --no-venv            skip the Python venv for 3D conversion (IFC / 3DM)
#   ./install.sh --build-app          also build Officina.app (needs Xcode command line tools)
set -e
REPO="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="${OFFICINA_HOME:-$HOME/.claude/office}"; NAME=""; PORT=""; LAUNCHD=1; VENV=1; APP=0
while [ $# -gt 0 ]; do case "$1" in
  --name) NAME="$2"; shift 2;; --port) PORT="$2"; shift 2;; --home) HOME_DIR="$2"; shift 2;;
  --no-launchd) LAUNCHD=0; shift;; --no-venv) VENV=0; shift;; --build-app) APP=1; shift;;
  -h|--help) sed -n 2,10p "$0"; exit 0;; *) echo "unknown option $1"; exit 1;; esac; done
[ "$(id -u)" = 0 ] && { echo "Do not run as root / with sudo."; exit 1; }
[ "$(uname)" = Darwin ] || echo "Note: made for macOS. The server also runs on Linux, but the LaunchAgents and the app do not."
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

echo "== 1/6 checking tools"
MISS=()
need() { command -v "$1" >/dev/null 2>&1 && printf '  ok       %s\n' "$1" || { printf '  missing  %s  (%s)\n' "$1" "$2"; MISS+=("$3"); }; }
need python3 "runs the server" python
need tmux "agents run in the background" tmux
need ttyd "terminal panels in the app" ttyd
need node "STEP files in the 3D viewer" node
need pdftoppm "PDF viewer + markup (poppler)" poppler
need claude "Claude Code CLI for the agents" ""
if [ ${#MISS[@]} -gt 0 ]; then
  L=$(printf '%s ' "${MISS[@]}" | sed 's/  */ /g; s/ $//')
  [ -n "$L" ] && echo "  Install the missing ones with Homebrew (https://brew.sh):  brew install $L"
  command -v claude >/dev/null || echo "  Claude Code: see https://docs.claude.com/en/docs/claude-code (then run 'claude' once to log in)"
  command -v python3 >/dev/null || { echo "python3 is required. Stop."; exit 1; }
fi

echo "== 2/6 data folder: $HOME_DIR"
mkdir -p "$HOME_DIR"/{log,cache,roles,agents,votes,markups,flow/hooks,notes}
[ -z "$NAME" ] && NAME="$( (id -F 2>/dev/null || echo You) | awk '{print $1}')"
if [ -f "$HOME_DIR/config.json" ]; then
  echo "  config.json exists: kept"
else
  python3 - "$REPO/config.example.json" "$HOME_DIR/config.json" "$NAME" "$PORT" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])); c.pop("_help", None)
c["human_name"] = sys.argv[3] or "You"
if sys.argv[4]: c["port"] = int(sys.argv[4])
json.dump(c, open(sys.argv[2], "w"), indent=1)
PY
  echo "  config.json written (edit team, names, colours, folders there)"
fi
for f in "$REPO"/examples/*.json "$REPO"/examples/flow/*.json; do
  rel="${f#$REPO/examples/}"; [ -e "$HOME_DIR/$rel" ] || cp "$f" "$HOME_DIR/$rel"
done
COORD=$(python3 -c 'import json,sys;print((json.load(open(sys.argv[1])).get("team") or [{"name":"Coordinator"}])[0]["name"])' "$HOME_DIR/config.json")
python3 - "$HOME_DIR/cards.json" "$COORD" <<'PY'
import json, sys
p, coord = sys.argv[1:]; d = json.load(open(p))
for c in d:
    if c.get("kind") == "welcome" and c.get("from") == "Coordinator": c["from"] = coord
json.dump(d, open(p, "w"), indent=1, ensure_ascii=False)
PY
for f in "$REPO"/roles/*.md; do b=$(basename "$f"); [ -e "$HOME_DIR/roles/$b" ] || cp "$f" "$HOME_DIR/roles/$b"; done
mkdir -p "$HOME/.claude/status"
echo "  roles/ templates copied (only missing ones)"

echo "== 3/6 Python venv for IFC / 3DM conversion"
if [ $VENV = 1 ]; then
  if [ ! -x "$HOME_DIR/venv/bin/python" ]; then python3 -m venv "$HOME_DIR/venv"; fi
  "$HOME_DIR/venv/bin/pip" install -q --upgrade pip
  "$HOME_DIR/venv/bin/pip" install -q ifcopenshell rhino3dm numpy mapbox_earcut shapely trimesh && echo "  venv ready: $HOME_DIR/venv" \
    || echo "  venv: some packages failed (the viewer then cannot open IFC / 3DM; PDF and STEP still work)"
else echo "  skipped (--no-venv)"; fi

echo "== 4/6 STEP converter (node)"
if command -v node >/dev/null && [ ! -d "$REPO/tools/node_modules/occt-import-js" ]; then (cd "$REPO/tools" && npm install --silent --no-audit --no-fund) && echo "  occt-import-js installed"; else echo "  ok or skipped"; fi

echo "== 5/6 LaunchAgents"
chmod +x "$REPO"/scripts/*.sh "$REPO"/scripts/*.py "$REPO"/app-mac/build.sh 2>/dev/null || true
if [ $LAUNCHD = 1 ] && [ "$(uname)" = Darwin ]; then
  python3 "$REPO/scripts/make_launchagents.py" "$REPO" "$HOME_DIR"
else echo "  skipped. Start the server by hand:  OFFICINA_HOME=\"$HOME_DIR\" python3 \"$REPO/app/server.py\""; fi

echo "== 6/6 Mac app"
if [ $APP = 1 ]; then "$REPO/app-mac/build.sh"; else echo "  skipped (add --build-app, or open http://127.0.0.1:$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("port",4242))' "$HOME_DIR/config.json")/ in a browser)"; fi

cat <<TXT

Done. Next steps
 1. Open Officina: http://127.0.0.1:$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("port",4242))' "$HOME_DIR/config.json")/
 2. Edit $HOME_DIR/config.json: your team (names, colours, roles), folders the viewer may open.
 3. Put "$REPO/scripts" on your PATH, or call the scripts with their full path.
 4. Optional, recommended: Claude Code hooks for the "waiting for you" signals. Add this to ~/.claude/settings.json yourself
    (merge with what is there; this installer does not edit it):

   "hooks": {
     "Notification": [{"hooks": [{"type": "command", "command": "'$REPO/scripts/hook-status.sh' notification"}]}],
     "Stop":         [{"hooks": [{"type": "command", "command": "'$REPO/scripts/hook-status.sh' stop"}]}]
   }

 5. Start your coordinator:  $REPO/scripts/coordinator-session.sh   (or the terminal panel in the app)
    and paste roles/coordinator.md + roles/_common.md as its first brief. README.md has the walkthrough.
TXT
