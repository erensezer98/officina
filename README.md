# Officina

A local office for a small team of **Claude Code agents** and one human.
Officina is a web page on your Mac (and an optional native app) that shows what every agent does, collects every question as a card,
tracks each deliverable from author to reviewer to filing, and lets you review PDFs and 3D models with markup. Everything stays on your machine.

> Officina does not run the agents. Each agent is a normal Claude Code session (in tmux or a Terminal window).
> Officina reads their transcripts (read-only) and gives them a few small commands to post cards, files, drafts and status.

## What you see

| Screen | What it does |
|---|---|
| **Team** | One row per agent: live state (working / idle / waiting for you), what it is doing, its helpers, who talks to whom. Click → its terminal or profile. |
| **For you** (cards) | Every question from the team, with option buttons. Your click goes straight back to the coordinator. |
| **Chat + terminal** | Your conversation with the coordinator, and a live terminal panel. |
| **Requests** | Agents tell you what *you* could do so they work better ("give the target folder up front"). You reply; the coordinator relays it at once. |
| **Artifacts library** | Every file the team produced, with status (for approval, filed, sent…), REV chains and "new" badges. |
| **Viewer** | PDF, images, IFC, STEP and 3DM (Rhino) in the browser. **Markup**: boxes + comments on PDFs, pins on 3D elements; "send" hands a report to the coordinator. |
| **Compare** | Two REVs of a PDF side by side or as a red/green overlay. |
| **Lanes** | One lane per deliverable: author → Judge → Folder Manager → you → sent. Shows who holds it and for how long; alarms when something is stuck. |
| **Timeline** | A simple Gantt from a JSON file your Procurer keeps. |
| **Profiles** | Per agent: role card, notes, open items, activity, helpers, permissions (read-only view + per-agent overrides), feedback and its own score trend. |
| **Drafts box** | Mail / chat texts the team prepared. You copy and send them yourself. |

## How we work (the operating model)

1. **One coordinator.** You talk to one agent. It routes work to the others, keeps the board true and turns every question into a card.
2. **Agents never ask you in their own window.** Questions go to the coordinator and become cards with 2–4 options.
   When a picture helps, the question comes as a small question PDF you can mark up.
   *Exception:* risky edits to the central model are confirmed in the CAD app / terminal itself.
3. **Every deliverable goes author → Judge → Folder Manager.** The Judge reviews with several *reviewer personas*
   (for example structural engineer, workshop, installer, first-glance reader) and sends PASS or a numbered change list.
   After PASS the Folder Manager files it and posts the link. Only then does it reach you.
4. **Your markup reopens the lane.** Mark up a PDF or 3D model and press *send*: the author gets your comments and a new REV starts.
5. **Drafts only.** Agents never send mail or messages. They prepare drafts; you send.
6. **Daily feedback round – not a competition.** Each evening every agent rates the others 1–10 and writes *what helped* and
   *what they need* (from you, the team, tools or context). Scores are only each agent's own trend. The Tech agent groups the
   "needs" and turns the top 3 into proposals (a tool, a shared context file, a brief template, a rule, earlier information).
7. **Requests page.** Agents file concrete, polite requests to you. You answer there.
8. **Weekly pain card.** Once a week you get a card: "1–2 tasks that felt slow this week". The Tech agent scouts tools and
   build ideas around them.
9. **Fresh sessions.** When an agent is idle and its context is large, restart it fresh: its role card and notes are the handover.

## Suggested team

Role-card templates are in [`roles/`](roles/). Copy, rename and adapt them; keep `_common.md` for everyone.

| Role | Purpose | Inputs → outputs | May / may not | Reports |
|---|---|---|---|---|
| **Coordinator** | Your single contact; routing; cards | your chat, card answers, markups → briefs, cards, tasks, drafts | may start/restart agents and write Officina data · may not do the specialists' work or send anything outside | short lines; questions only as cards |
| **Modeller** | 3D models; every drawing / export made from the model | briefs, markups, change lists → PDF / IFC / STEP / 3DM + source model, in its work folder | may edit its own copies · may not edit the central model without your OK, file to shared folders, or send | one message per step: what, REV, path |
| **Judge** | Review before you see it | submit message + files → PASS / change list | may read, render, measure, run checks · may not edit the author's files or add demands outside the brief | verdict line first, then the list |
| **Folder Manager** | File standard, filing, superseding, staging for suppliers | "please file" after PASS → filed copy + link + artifact entry | may copy / rename / move in project folders · may not delete, share or send | one line: where, link, what was superseded |
| **Procurer** | Suppliers, quotes, orders, timeline | sources you allow → tables, `timeline.json`, drafts | may write in its own folder · may not send, accept offers or share | table first, then one line |
| **Tech** | Workflow review, tools, build ideas, scores | transcripts, logs, Officina data → reports, proposals, `scores.json` | may read and report · may not install or change settings without your OK | problem → evidence → fix → saving → effort |
| *CAD specialist* (optional) | Parametric parts (threads, sheet metal, animations) | brief → native file + STEP + renders | own documents only, one per job | one message per step |

The team list (names, colours, roles, work folders) lives in `config.json`. The first member is the coordinator.
Lane detection expects a reviewer and a filer; their names are set by `"reviewer"` and `"filer"` (default Judge / Folder Manager).

## Install (macOS)

```bash
git clone <this repo> officina && cd officina
./install.sh --name "Ada"           # add --build-app for the native app, --port 4242 to change the port
```

`install.sh` never uses `sudo` and never overwrites existing data. It:
- checks `python3`, `tmux`, `ttyd`, `node`, `poppler` and `claude`, and prints the `brew install …` line for the missing ones;
- creates the data folder (`~/.claude/office`, or `$OFFICINA_HOME`): `config.json` from `config.example.json`, empty data files,
  the welcome cards and the role templates;
- creates a Python venv for 3D conversion (IfcOpenShell, rhino3dm, numpy, mapbox_earcut, shapely, trimesh) and installs the STEP reader (`npm`);
- writes LaunchAgents `com.officina.*` with your own paths (server, terminal panels, team snapshot/autostart, back-from-sleep brief,
  weekly pain card, and one per routine in `config.json`);
- optionally builds `~/Applications/Officina.app`.

Then open **http://127.0.0.1:4242/**. `./uninstall.sh` removes the LaunchAgents and the app; `./uninstall.sh --purge` also deletes the data (asks first).

What you need: macOS 12+, Homebrew, Python 3.10+, Claude Code (logged in), and `brew install tmux ttyd node poppler`.
Optional: Google Chrome (screenshots for agents), Tailscale (phone access), Xcode command line tools (native app).

### Claude Code hooks (recommended)

Hooks give Officina an exact "waiting for your permission / input" signal. The installer prints the snippet; add it to
`~/.claude/settings.json` yourself (it does not edit your settings):

```json
"hooks": {
  "Notification": [{"hooks": [{"type": "command", "command": "'/path/to/officina/scripts/hook-status.sh' notification"}]}],
  "Stop":         [{"hooks": [{"type": "command", "command": "'/path/to/officina/scripts/hook-status.sh' stop"}]}]
}
```

### Configuration (`config.json`)

| Key | Default | Meaning |
|---|---|---|
| `port` | 4242 | web port (always bound to 127.0.0.1) |
| `human_name` | your macOS first name | shown on cards, chat and votes |
| `team` | 6 roles | `[{name, color, role, slug?, tmux?, work?}]`, first = coordinator |
| `reviewer`, `filer` | Judge, Folder Manager | who moves a lane to "reviewed" / "filed" |
| `file_roots` | ~/Documents, ~/Desktop, ~/Downloads | the only folders the viewer may open files from |
| `work_dir`, `notes_dir` | ~/Documents, `<office>/notes` | agents' work folders (`work` per member) and handover notes |
| `timeline_file` | `<office>/timeline.json` | the Procurer's timeline |
| `tailnet_ip` | empty | also listen on this private Tailscale IP (e.g. for your phone); never 0.0.0.0 |
| `terminal_port`, `agents_terminal_port` | 7681, 7682 | ttyd panels (localhost only) |
| `push_script` | empty | optional phone push: a script called with "Title" "Text" [url] (see `scripts/push-ntfy.example.sh`) |
| `routines` | Tech's three | `[{agent, routine, weekdays, hour, minute}]`; the scheduler types `ROUTINE <name>` into that agent's tmux session |
| `timezone` | system | quiet hours for alarms (23:00–07:30) |

After you change ports or routines: `python3 scripts/make_launchagents.py "$PWD" ~/.claude/office`.

## First start

1. **Open Officina.** You see **For you** with four welcome cards (cards, lanes + markup, feedback round, drafts + safety). Tap them; the answers go to the coordinator.
2. **Start the coordinator:** click the terminal panel (or run `scripts/coordinator-session.sh`). Give it `roles/coordinator.md` and `roles/_common.md` as its brief.
3. **Start the other agents** in tmux, one session per agent, named like the role slug (`modeller`, `judge`, …):
   `tmux new -d -s judge "claude -n 'Judge' --append-system-prompt-file ~/.claude/office/roles/judge.md"`.
   Officina finds them by their session name. Running agents in Terminal windows also works; `scripts/move-agent.sh "Judge"` moves one into tmux.
4. **Give agents the helper commands.** Put `scripts/` on their PATH (or use full paths):
   `agent-status.sh`, `office.sh card|task|draft|artifact|view|compare|flow|request`.
5. **Work.** Send a task in the chat. Watch it appear under the agent, then in **Lanes**, then in **Artifacts**.

## Safety rules we recommend

- **Permission denied = stop and ask.** An agent never tries another route to do a denied action.
- **No external sends.** Mail, chat and shares are drafts; the human sends. Staged supplier files are "not sent" until you say so.
- **Backups before model edits.** Dated copy in the agent's own folder first; check the CAD lock file before editing a shared model.
- **One agent test document in the CAD app.** Agents script in their own document, never in your open model.
- **Read-only by default.** Officina itself only reads transcripts and writes its own data folder. Per-agent permission overrides are written only
  after a confirm click, to `<office>/agents/<slug>.settings.json` (used with `--settings` at the agent's next restart).
- **Localhost only.** The server binds to 127.0.0.1 (plus an optional private Tailscale IP). Do not expose it to the internet.

## Data files (in the office folder)

`cards.json`, `tasks.json`, `artifacts.json`, `drafts.json`, `requests.json`, `routines.json`, `view.json`, `flow.jsonl`, `scores.json`,
`scores-history.json`, `votes/<day>/<name>.json`, `markups/`, `cache/`, `log/`. They hold your project data; **never commit them**
(`.gitignore` covers the repo; the data folder lives outside it).

## Folder layout

```
app/        server.py (stdlib HTTP server), settings.py (config), flow.py (lanes), profile_api.py, pages + JS
tools/      ifc2glb.py, 3dm2glb.py, step2glb.js (+ package.json)  – converters for the 3D viewer
scripts/    office.sh, agent-status.sh, hook-status.sh, coordinator-session.sh, agent-attach.sh, move-agent.sh,
            team-snapshot.py, team-autostart.sh, routine.sh, back-check.sh, weekly-pain-card.py, shot.sh, make_launchagents.py
app-mac/    Officina.swift + build.sh (native window, reads port + team from config.json)
roles/      role-card templates
examples/   empty data files + welcome cards
```

## Test without touching an existing install

```bash
T=$(mktemp -d); HOME=$T ./install.sh --no-launchd --no-venv --port 4343
HOME=$T python3 app/server.py          # then open http://127.0.0.1:4343/
HOME=$T python3 app/flow.py --test     # lane + alarm self-tests
```
