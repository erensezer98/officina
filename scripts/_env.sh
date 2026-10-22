# Shared by the Officina scripts: office folder, PATH, and values from config.json.
OFFICINA_HOME="${OFFICINA_HOME:-$HOME/.claude/office}"
export OFFICINA_HOME
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# cfg <key> [default]   e.g. cfg port 4242 · cfg human_name You
cfg() {
  python3 - "$OFFICINA_HOME" "$1" "${2:-}" <<'PY'
import json, os, sys
try: c = json.load(open(os.path.join(sys.argv[1], "config.json")))
except Exception: c = {}
v = c.get(sys.argv[2])
print(sys.argv[3] if v in (None, "") else (json.dumps(v) if isinstance(v, (dict, list)) else v))
PY
}
# team_field <field>   one line per team member (name | slug | tmux)
team_field() {
  python3 - "$OFFICINA_HOME" "$1" <<'PY'
import json, os, re, sys
try: t = json.load(open(os.path.join(sys.argv[1], "config.json"))).get("team") or []
except Exception: t = []
t = t or [{"name": "Coordinator"}]
for m in t:
    slug = m.get("slug") or re.sub(r"[^a-z0-9]+", "-", m["name"].lower()).strip("-")
    print({"name": m["name"], "slug": slug, "tmux": m.get("tmux") or slug}[sys.argv[2]])
PY
}
PORT="$(cfg port 4242)"
COORD="$(team_field name | head -1)"
COORD_SLUG="$(team_field tmux | head -1)"
