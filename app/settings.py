"""Officina settings: one config file, everything else derived from $HOME.

Config file: $OFFICINA_HOME/config.json (default ~/.claude/office/config.json). See config.example.json.
Environment overrides (handy for tests): OFFICINA_HOME, OFFICINA_PORT.
"""
import json, os, re, shutil

HOME = os.path.expanduser("~")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # the installed package folder
OFFICE = os.path.expanduser(os.environ.get("OFFICINA_HOME") or os.path.join(HOME, ".claude", "office"))
os.makedirs(OFFICE, exist_ok=True)


def _load():
    try:
        return json.load(open(os.path.join(OFFICE, "config.json")))
    except Exception:
        return {}


CFG = _load()

DEFAULT_TEAM = [
    {"name": "Coordinator", "color": "#c23b2e", "role": "Coordinator · routes work, turns questions into cards"},
    {"name": "Modeller", "color": "#e3b13b", "role": "Modeller · 3D models and drawings"},
    {"name": "Judge", "color": "#a9a59d", "role": "Judge · reviews every deliverable"},
    {"name": "Folder Manager", "color": "#3f6fb0", "role": "Folder Manager · file standard, filing, staging"},
    {"name": "Procurer", "color": "#e07f3a", "role": "Procurer · suppliers, quotes, timeline"},
    {"name": "Tech", "color": "#8a7fa3", "role": "Tech · workflow review, tools, scores"},
]

PORT = int(os.environ.get("OFFICINA_PORT") or CFG.get("port", 4242))
TEAM = CFG.get("team") or DEFAULT_TEAM
COORD = TEAM[0]["name"]                                   # first team member = the coordinator
HUMAN = CFG.get("human_name") or "You"
ORDER = [m["name"] for m in TEAM]
COLORS = {m["name"]: m.get("color", "#8a8478") for m in TEAM}
ROLES = {m["name"]: m.get("role", "") for m in TEAM}
TAILNET_IP = CFG.get("tailnet_ip", "")                    # optional: also listen on this private (Tailscale) IP

CLAUDE = os.path.join(HOME, ".claude")
SESSIONS = os.path.join(CLAUDE, "sessions")
STATUS = os.path.join(CLAUDE, "status")
# Claude Code keeps transcripts in ~/.claude/projects/<cwd with non-alphanumerics replaced by '-'>/
PROJECTS = os.path.expanduser(CFG.get("projects_dir") or os.path.join(CLAUDE, "projects", re.sub(r"[^A-Za-z0-9]", "-", HOME)))
WAKE = os.path.expanduser(CFG.get("wake_file") or os.path.join(OFFICE, "wake.txt"))   # inbox the coordinator watches
FILE_LOG = os.path.expanduser(CFG.get("file_log") or os.path.join(OFFICE, "file-moves.md"))
TIMELINE = os.path.expanduser(CFG.get("timeline_file") or os.path.join(OFFICE, "timeline.json"))
PUSH = os.path.expanduser(CFG.get("push_script") or "")  # optional phone push: script "Title" "Text" [url]
LOCATION = os.path.expanduser(CFG.get("location_script") or "")   # optional: prints where you are (e.g. "home")

CACHE = os.path.join(OFFICE, "cache")
os.makedirs(CACHE, exist_ok=True)
# The viewer may only serve files below these folders (your own folders by default) + its cache.
ROOTS = tuple(os.path.join(os.path.realpath(os.path.expanduser(r)), "") for r in
              (CFG.get("file_roots") or ["~/Documents", "~/Desktop", "~/Downloads"])) + (os.path.join(CACHE, ""),)

TOOLS = os.path.join(REPO, "tools")
VENV_PY = os.path.expanduser(CFG.get("geo_python") or os.path.join(OFFICE, "venv", "bin", "python"))   # IfcOpenShell / rhino3dm


def which(name):
    """Full path of a command line tool (Homebrew on Apple silicon or Intel, or PATH)."""
    for p in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if os.path.exists(p):
            return p
    return shutil.which(name) or name


def page_vars():
    """Values the server fills into the HTML pages ({{COORD}}, {{HUMAN}}, {{TEAM_JSON}} ...)."""
    return {"{{COORD}}": COORD, "{{HUMAN}}": HUMAN, "{{HUMAN_INITIAL}}": (HUMAN[:1] or "Y").upper(),
            "{{TEAM_JSON}}": json.dumps([{**m, "name": m["name"]} for m in TEAM]), "{{PORT}}": str(PORT),
            "{{TIMELINE}}": TIMELINE.replace(HOME, "~"), "{{COORD_RX}}": re.escape(COORD).replace("\\ ", " "),
            "{{TTY_PORT}}": str(CFG.get("terminal_port", 7681)), "{{TTY_AGENTS_PORT}}": str(CFG.get("agents_terminal_port", 7682)),
            "{{TEAM_OPTIONS}}": "".join(f"<option>{m['name']}</option>" for m in TEAM[1:])}


def render(path):
    """Read an HTML/JS file of the app and fill in the page variables."""
    b = open(path, encoding="utf-8").read()
    for k, v in page_vars().items():
        b = b.replace(k, v)
    return b.encode("utf-8")
