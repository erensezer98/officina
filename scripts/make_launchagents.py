#!/usr/bin/env python3
"""Write and load Officina's LaunchAgents (~/Library/LaunchAgents/com.officina.*.plist) for this user. Called by install.sh.
Usage: make_launchagents.py <repo> <office dir> [--dry-run DIR]   (re-run after you change ports or routines in config.json)
--dry-run DIR: only write the plists into DIR (no launchctl), to inspect them."""
import json, os, plistlib, re, shutil, subprocess, sys
REPO, OFFICE = sys.argv[1], sys.argv[2]
DRY = sys.argv[sys.argv.index("--dry-run") + 1] if "--dry-run" in sys.argv else None
H = os.path.expanduser("~"); LA = DRY or f"{H}/Library/LaunchAgents"; os.makedirs(LA, exist_ok=True)
cfg = json.load(open(f"{OFFICE}/config.json"))
PATH = f"{H}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ENV = {"OFFICINA_HOME": OFFICE, "PATH": PATH, "LANG": "en_US.UTF-8"}
py = shutil.which("python3") or "/usr/bin/python3"; ttyd = shutil.which("ttyd", path=PATH); S = f"{REPO}/scripts"
TTYD_OPTS = ["-W", "-t", "fontFamily=Menlo, monospace", "-t", "fontSize=14", "-t", "disableLeaveAlert=true", "-t", "cursorBlink=true"]
jobs = {
    "server": {"ProgramArguments": [py, f"{REPO}/app/server.py"], "RunAtLoad": True, "KeepAlive": True, "log": "officina.log"},
    "team-snapshot": {"ProgramArguments": [py, f"{S}/team-snapshot.py"], "StartInterval": 600, "RunAtLoad": True},
    "team-autostart": {"ProgramArguments": ["/bin/bash", f"{S}/team-autostart.sh"], "RunAtLoad": True, "log": "autostart.log"},
    "back-check": {"ProgramArguments": ["/bin/bash", f"{S}/back-check.sh"], "StartInterval": 300, "RunAtLoad": True},
    "weekly-pain-card": {"ProgramArguments": [py, f"{S}/weekly-pain-card.py"], "StartCalendarInterval": [{"Weekday": 3, "Hour": 17, "Minute": 30}]},
}
if ttyd:
    jobs["terminal"] = {"ProgramArguments": [ttyd, "-i", "127.0.0.1", "-p", str(cfg.get("terminal_port", 7681)), *TTYD_OPTS, f"{S}/coordinator-session.sh"],
                        "RunAtLoad": True, "KeepAlive": True, "log": "ttyd.log"}
    jobs["agentterm"] = {"ProgramArguments": [ttyd, "-i", "127.0.0.1", "-p", str(cfg.get("agents_terminal_port", 7682)), *TTYD_OPTS, "-a", f"{S}/agent-attach.sh"],
                         "RunAtLoad": True, "KeepAlive": True, "log": "agentterm.log"}
for i, r in enumerate(cfg.get("routines") or []):
    when = [{"Weekday": d % 7, "Hour": r["hour"], "Minute": r["minute"]} for d in (r.get("weekdays") or [1, 2, 3, 4, 5])]
    jobs[f"routine-{re.sub(r'[^a-z0-9]+', '-', (r['agent'] + '-' + r['routine']).lower())}"] = {
        "ProgramArguments": ["/bin/bash", f"{S}/routine.sh", r["agent"], r["routine"]], "StartCalendarInterval": when}
uid = os.getuid()
for f in os.listdir(LA):                                        # remove routines that are no longer in config.json
    if not DRY and f.startswith("com.officina.routine-") and f[len("com.officina."):-len(".plist")] not in jobs:
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", f"{LA}/{f}"], capture_output=True); os.remove(f"{LA}/{f}")
for name, j in jobs.items():
    label = f"com.officina.{name}"; p = f"{LA}/{label}.plist"; log = j.pop("log", None)
    d = {"Label": label, "EnvironmentVariables": ENV, **j}
    if log:
        d["StandardOutPath"] = d["StandardErrorPath"] = f"{OFFICE}/{log}"
    if not DRY:
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", p], capture_output=True)
    with open(p, "wb") as f:
        plistlib.dump(d, f)
    if DRY:
        print(f"  written  {label}"); continue
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", p], capture_output=True, text=True)
    print(f"  {'loaded ' if r.returncode == 0 else 'FAILED '} {label}" + ("" if r.returncode == 0 else f"  ({r.stderr.strip()[:80]})"))
if not ttyd:
    print("  ttyd not found: terminal panels skipped (brew install ttyd, then re-run this script)")
