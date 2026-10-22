"""Officina · agent profile page data.

GET  /api/profile?name=<agent>      -> profile(name, srv)
POST /api/profile/perm {slug, op, list, rule} -> perm_change(data, srv)

Reads:  <office>/roles/<slug>.md                   role card (Markdown)
        <notes_dir>/<Name> notes.md                handover notes (last entries)
        <claude projects dir>/memory/              memory rules named in the role card
        <office>/scores.json, scores-history.json  scores written by the Tech agent (may be missing)
        ~/.claude/settings.json, settings.local.json (+ project settings of the agent's cwd)  READ ONLY
        the agent's transcript (last 7 days): tools, helpers, activity, steps, messages, written files
Writes: ONLY <office>/agents/<slug>.settings.json (per-agent overrides, used with `--settings` at the next restart)
        + one line in <office>/perm-changes.log + a wake line for the coordinator.
Never writes ~/.claude/settings*.json.

`srv` is the running server module (team(), sessions(), subagents(), ctx_tokens(), tracks(), CHAT, jload, wake, tool_line, norm_agent).
"""
import json, os, re, time, datetime, threading, glob, collections
import settings as S

HOME = S.HOME
OFFICE = S.OFFICE
ROLES, AGDIR = f"{OFFICE}/roles", f"{OFFICE}/agents"
SCORES, PERMLOG = f"{OFFICE}/scores.json", f"{OFFICE}/perm-changes.log"
SCORES_HIST = f"{OFFICE}/scores-history.json"   # {"days":{"YYYY-MM-DD":{"<Name>":{"overall":..,"metrics":{..}}}}}
NOTES = os.path.expanduser(S.CFG.get("notes_dir") or f"{OFFICE}/notes")
MEMDIR = f"{S.PROJECTS}/memory"
WIP = os.path.expanduser(S.CFG.get("work_dir") or "~/Documents")
COORD, HUMAN = S.COORD, S.HUMAN

# per team member (config.json "team"): slug (roles/<slug>.md, agents/<slug>.settings.json) · tmux session · work folders with out/
_slug = lambda n: re.sub(r"[^a-z0-9]+", "-", (n or "").lower()).strip("-")
SLUG = {m["name"]: m.get("slug") or _slug(m["name"]) for m in S.TEAM}
TMUX = {m["name"]: m.get("tmux") or SLUG[m["name"]] for m in S.TEAM}
WORK = {m["name"]: m.get("work", []) for m in S.TEAM}            # folders below work_dir
ROLE_LINE = {m["name"]: ((m.get("role") or "agent").split(" · ", 1)[-1] if " · " in (m.get("role") or "") else (m.get("role") or "agent"))[:60] for m in S.TEAM}
DAY = 86400


def slug_of(name):
    return SLUG.get(name) or re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def name_of_slug(s):
    return next((n for n, v in SLUG.items() if v == s), None)


def _read(p, limit=400_000):
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except Exception:
        return None


# ---------------- role card ----------------
def role_card(name):
    s = slug_of(name)
    for c in [s, TMUX.get(name, ""), (name or "").lower().replace(" ", "-")]:
        if c and os.path.exists(f"{ROLES}/{c}.md"):
            p = f"{ROLES}/{c}.md"
            return {"path": p, "text": _read(p) or "", "mtime": int(os.path.getmtime(p))}
    return {"path": f"{ROLES}/{s}.md", "text": "", "mtime": None}


def md_sections(text):
    """'## Heading' -> body (first-level-2 sections only)."""
    out, cur, buf = collections.OrderedDict(), None, []
    for ln in (text or "").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", ln)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m[1], []
        elif cur is not None:
            buf.append(ln)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def pick(secs, pat):
    for k, v in secs.items():
        if re.search(pat, k, re.I):
            return {"title": k, "md": v}
    return None


def bullets(md):
    out = []
    for ln in (md or "").splitlines():
        m = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)", ln)
        if m:
            out.append(m[1].strip())
    return out


def personas(secs):
    s = pick(secs, r"persona")
    if not s:
        return []
    out = []
    for b in bullets(s["md"]):
        m = re.match(r"\*\*([^*]+?):?\*\*:?\s*(.*)", b)
        if m:
            out.append({"name": m[1].strip().rstrip(":"), "what": m[2].strip()})
    return out


# ---------------- notes + memory ----------------
def notes(name, n=4):
    p = f"{NOTES}/{name} notes.md"
    if not os.path.exists(p):
        return {"path": p, "entries": [], "exists": False}
    try:
        with open(p, "rb") as f:
            f.seek(max(0, os.path.getsize(p) - 16000)); t = f.read().decode("utf-8", "replace")
    except Exception:
        return {"path": p, "entries": [], "exists": True}
    parts = re.split(r"(?m)^(?=#{2,3}\s)", t)
    parts = [x.strip() for x in parts if x.strip() and re.match(r"#{2,3}\s", x.strip())]
    if not parts:                                            # no headings: dated paragraphs
        parts = [x.strip() for x in re.split(r"\n\s*\n", t) if x.strip()]
    return {"path": p, "entries": parts[-n:][::-1], "exists": True, "mtime": int(os.path.getmtime(p))}


def memory_index():
    idx = {}
    for ln in (_read(f"{MEMDIR}/MEMORY.md") or "").splitlines():
        m = re.match(r"-\s*\[([^\]]+)\]\(([^)]+)\)\s*[—-]\s*(.*)", ln)
        if m:
            idx[m[2].replace(".md", "")] = {"title": m[1], "desc": m[3].strip()}
    return idx


def memory_links(name, card):
    idx = memory_index(); want = []
    m = re.search(r"Memory[^:\n]*:\s*([^\n]+)", card or "")
    if m:
        want = [x for x in re.findall(r"[a-z0-9][a-z0-9-]{2,}", m[1]) if x not in ("auto-loaded", "index", "memory")]
    lab = r"\b" + re.escape(name) + r"\b"
    named = [k for k, v in idx.items() if re.search(lab, v["title"] + " " + v["desc"], re.I) and k not in want]
    out = []
    for k, src in [(k, "card") for k in want] + [(k, "mentions") for k in named]:
        f = f"{MEMDIR}/{k}.md"; body = _read(f, 4000) if os.path.exists(f) else None
        if body:
            body = re.sub(r"^---[\s\S]*?---\s*", "", body).strip()
        i = idx.get(k, {})
        out.append({"slug": k, "title": i.get("title") or k.replace("-", " "), "desc": i.get("desc", ""), "body": (body or "")[:1500],
                    "exists": bool(body), "from": src})
    return out[:30]


# ---------------- transcript scan (last 7 days, incremental, background) ----------------
RX_PATH = re.compile(re.escape(HOME.encode()) + rb"/[^\"\\\n]{3,300}?\.(?:pdf|ifc|3dm|glb|stp|step|sat|dwg|dxf|xlsx|csv|png|mp4|zip)\b", re.I)


def ts_of(raw):
    m = re.search(rb'"timestamp":"([^"]+)"', raw)
    if not m:
        return None
    try:
        return datetime.datetime.fromisoformat(m[1].decode().replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def offset_since(path, t0):
    """Binary search: byte offset of the first line with timestamp >= t0 (transcripts are append-only, time-ordered)."""
    size = os.path.getsize(path); lo, hi = 0, size
    with open(path, "rb") as f:
        def at(pos):
            f.seek(pos)
            if pos:
                f.readline()
            start = f.tell()
            for _ in range(40):
                ln = f.readline()
                if not ln:
                    return start, None
                t = ts_of(ln[:4000]) if b'"timestamp"' in ln[:4000] else None
                if t:
                    return start, t
            return start, None
        while hi - lo > 1_000_000:
            mid = (lo + hi) // 2; _, t = at(mid)
            if t is None or t >= t0:
                hi = mid
            else:
                lo = mid
        return at(lo)[0]


class Scan:
    def __init__(self, path, srv):
        self.path, self.srv = path, srv
        self.lock, self.busy = threading.Lock(), False
        self.off, self.done_first = None, False
        self.tools, self.mcp = collections.Counter(), collections.Counter()
        self.buckets = collections.Counter()                  # 10-min bucket -> assistant events
        self.steps = collections.deque(maxlen=10)
        self.msgs = collections.deque(maxlen=40)
        self.calls = collections.OrderedDict()                # tool_use id -> helper record
        self.aid = {}
        self.files = collections.OrderedDict()                # paths it wrote / named
        self.model, self.first, self.mode = None, None, None

    def start(self):
        with self.lock:
            if self.busy:
                return
            self.busy = True
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            if self.off is None:
                self.off = offset_since(self.path, time.time() - 7 * DAY)
            size = os.path.getsize(self.path)
            with open(self.path, "rb") as f:
                f.seek(self.off)
                while True:
                    raw = f.readline()
                    if not raw or not raw.endswith(b"\n"):
                        break
                    self.off += len(raw)
                    try:
                        self.line(raw)
                    except Exception:
                        pass
                    if self.off >= size and not self.done_first:
                        pass
            self.done_first = True
        finally:
            self.busy = False

    def line(self, raw):
        head = raw[:300]
        if b'"type":"permission-mode"' in head:
            m = re.search(rb'"permissionMode":"(\w+)"', raw); self.mode = m[1].decode() if m else self.mode; return
        isA = b'"type":"assistant"' in raw[:2000] or raw.startswith(b'{"parentUuid"') and b'"role":"assistant"' in raw[:3000]
        if b'"isSidechain":true' in raw[:600]:
            return
        if isA and b'"role":"assistant"' in raw:
            d = json.loads(raw)
            if d.get("type") != "assistant" or d.get("isSidechain"):
                return
            ts = self.srv.iso_ts(d.get("timestamp")); m = d.get("message") or {}
            self.first = self.first or ts; self.model = m.get("model") or self.model
            self.buckets[int(ts // 600)] += 1
            for c in m.get("content") or []:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                n = c.get("name", "tool"); i = c.get("input") or {}
                if n.startswith("mcp__"):
                    parts = n.split("__"); self.mcp[parts[1] if len(parts) > 1 else n] += 1
                self.tools[n] += 1
                tl = self.srv.tool_line(c); self.steps.append({"ts": ts, "tool": tl["tool"], "text": tl["text"][:160]})
                if n == "SendMessage":
                    to = str(i.get("to") or i.get("recipient") or "")
                    if not re.fullmatch(r"a[0-9a-f]{12,}", to):
                        summ = i.get("summary") or (str(i.get("message") or "").strip().splitlines() or [""])[0]
                        self.msgs.append({"ts": ts, "dir": "out", "peer": self.srv.norm_agent(to), "text": summ[:200]})
                elif n in ("Agent", "Task"):
                    self.calls[c["id"]] = {"desc": str(i.get("description") or i.get("subagent_type") or "helper")[:90],
                                           "type": i.get("subagent_type") or "", "ts": ts, "bg": bool(i.get("run_in_background")),
                                           "dur": None, "tokens": None, "tools": None, "state": "running"}
                    while len(self.calls) > 400:
                        self.calls.popitem(last=False)
                fp = i.get("file_path") if n in ("Write", "Edit", "NotebookEdit") else None
                if fp:
                    self.files[fp] = ts
            for p in RX_PATH.findall(raw):
                try:
                    self.files[p.decode("utf-8")] = ts
                except Exception:
                    pass
            while len(self.files) > 3000:
                self.files.popitem(last=False)
            return
        pend = [k for k, v in self.calls.items() if v["state"] == "running"]
        hasN = b"task-notification" in raw; hasM = b"cross-session-message" in raw or b"<agent-message" in raw
        hasR = any(k.encode() in raw for k in pend)
        if not (hasN or hasM or hasR):
            return
        d = json.loads(raw); ts = self.srv.iso_ts(d.get("timestamp"))
        txt = raw.decode("utf-8", "replace")
        if hasN:
            for b in re.finditer(r"<task-notification>(.*?)</task-notification>", txt.replace("\\n", "\n"), re.S):
                tid = re.search(r"<tool-use-id>(toolu_\w+)</tool-use-id>", b[1]); st = re.search(r"<status>(\w+)</status>", b[1])
                if not tid or tid[1] not in self.calls:
                    continue
                r = self.calls[tid[1]]
                if st and st[1] != "running":
                    r["state"] = st[1]
                du = re.search(r"<duration_ms>(\d+)</duration_ms>", b[1]); tk = re.search(r"<subagent_tokens>(\d+)", b[1]); tu = re.search(r"<tool_uses>(\d+)", b[1])
                if du:
                    r["dur"] = int(du[1]) / 1000
                if tk:
                    r["tokens"] = int(tk[1])
                if tu:
                    r["tools"] = int(tu[1])
        if d.get("type") != "user" or d.get("isSidechain"):
            return
        c = (d.get("message") or {}).get("content")
        if hasM and isinstance(c, str):
            frm = re.search(r'from-name="([^"]+)"', c)
            body = [x.strip() for x in re.sub(r"<[^>]+>", "", c).splitlines() if x.strip() and not x.startswith("Another Claude session")]
            if frm:
                self.msgs.append({"ts": ts, "dir": "in", "peer": self.srv.norm_agent(frm[1]), "text": (body[0] if body else "")[:200]})
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "tool_result" and p.get("tool_use_id") in self.calls:
                    r = self.calls[p["tool_use_id"]]; tur = d.get("toolUseResult")
                    if isinstance(tur, dict) and (tur.get("isAsync") or tur.get("status") == "async_launched"):
                        r["bg"] = True; r["aid"] = tur.get("agentId")
                    else:
                        r["state"] = "error" if p.get("is_error") else "completed"
                        if isinstance(tur, dict) and tur.get("totalDurationMs"):
                            r["dur"] = tur["totalDurationMs"] / 1000; r["tokens"] = tur.get("totalTokens"); r["tools"] = tur.get("totalToolUseCount")
                        elif r["dur"] is None:
                            r["dur"] = max(0, ts - r["ts"])

    def snapshot(self):
        now = time.time(); b = self.buckets
        b0 = int(now // 600)
        day = [b.get(b0 - 143 + i, 0) for i in range(144)]                         # 24 h · 10-min cells
        h0 = int(now // 3600)
        week = [sum(b.get(k, 0) for k in range((h0 - 167 + i) * 6, (h0 - 167 + i) * 6 + 6)) for i in range(168)]   # 7 d · 1-h cells
        hist = {}
        for r in self.calls.values():
            if now - r["ts"] > 7 * DAY:
                continue
            k = re.sub(r"^[A-Z][\w ]{1,20}:\s*", "", r["desc"]).strip()          # "Name: task" -> "task"
            k = re.sub(r"\s+(REV\d+|#\d+|\d+/\d+|round \d+|r\d+)$", "", k, flags=re.I)
            h = hist.setdefault(k.lower(), {"desc": k, "type": r["type"], "count": 0, "durs": [], "last": 0, "fail": 0, "tokens": []})
            h["count"] += 1; h["last"] = max(h["last"], r["ts"])
            if r["dur"]:
                h["durs"].append(r["dur"])
            if r.get("tokens"):
                h["tokens"].append(r["tokens"])
            if r["state"] in ("error", "failed", "killed", "stopped"):
                h["fail"] += 1
        hl = sorted(hist.values(), key=lambda h: -h["last"])
        for h in hl:
            d = h.pop("durs"); t = h.pop("tokens")
            h["avg"] = round(sum(d) / len(d)) if d else None; h["timed"] = len(d)
            h["avgTokens"] = round(sum(t) / len(t)) if t else None; h["last"] = int(h["last"])
        return {"ready": self.done_first, "model": self.model, "mode": self.mode, "first": int(self.first) if self.first else None,
                "tools": self.tools.most_common(14), "mcp": self.mcp.most_common(10), "day": day, "week": week,
                "steps": list(self.steps)[::-1], "msgs": list(self.msgs)[::-1][:20], "helpers": hl[:30],
                "helperTotal": sum(h["count"] for h in hl), "files": list(self.files.keys())}


SCANS, SLOCK = {}, threading.Lock()


def scan_for(path, srv):
    with SLOCK:
        s = SCANS.get(path)
        if not s:
            s = SCANS[path] = Scan(path, srv)
    if not s.busy:
        s.start()
    return s


def merge(snaps):
    """The coordinator can have several transcripts in 7 days: merge counters and lists."""
    if len(snaps) == 1:
        return snaps[0]
    out = dict(snaps[-1]); tc, mc = collections.Counter(), collections.Counter()
    for s in snaps:
        tc.update(dict(s["tools"])); mc.update(dict(s["mcp"]))
    out["tools"], out["mcp"] = tc.most_common(14), mc.most_common(10)
    out["day"] = [sum(x) for x in zip(*[s["day"] for s in snaps])]; out["week"] = [sum(x) for x in zip(*[s["week"] for s in snaps])]
    out["ready"] = all(s["ready"] for s in snaps); out["files"] = sum([s["files"] for s in snaps], [])
    out["first"] = min([s["first"] for s in snaps if s["first"]] or [None]) if any(s["first"] for s in snaps) else None
    hs = {}
    for s in snaps:
        for h in s["helpers"]:
            k = h["desc"].lower()
            if k in hs:
                a = hs[k]; n = a["timed"] + h["timed"]
                a["avg"] = round(((a["avg"] or 0) * a["timed"] + (h["avg"] or 0) * h["timed"]) / n) if n else None
                a["count"] += h["count"]; a["fail"] += h["fail"]; a["timed"] = n; a["last"] = max(a["last"], h["last"])
            else:
                hs[k] = dict(h)
    out["helpers"] = sorted(hs.values(), key=lambda h: -h["last"])[:30]; out["helperTotal"] = sum(h["count"] for h in hs.values())
    return out


# ---------------- deliverables ----------------
def deliverables(name, files, srv):
    seen = {os.path.basename(p).lower() for p in files}
    full = set(files)
    arts = []
    for a in srv.jload("artifacts.json", []):
        cands = [a.get("path") or "", a.get("master") or "", a.get("ftpPath") or ""]
        if any(c and (c in full or os.path.basename(c).lower() in seen) for c in cands):
            arts.append({k: a.get(k) for k in ("title", "status", "path", "url", "pkg", "date")})
    outs = []
    for w in WORK.get(name, []):
        for f in glob.glob(f"{WIP}/{glob.escape(w)}/**/out/*", recursive=True):
            if os.path.isfile(f) and not os.path.basename(f).startswith("."):
                outs.append((os.path.getmtime(f), f))
    outs.sort(reverse=True)
    return {"artifacts": arts[:25], "out": [{"path": f, "mtime": int(t), "task": os.path.basename(os.path.dirname(os.path.dirname(f)))} for t, f in outs[:14]],
            "outTotal": len(outs)}


# ---------------- permissions ----------------
PLAIN_TOOL = {"Bash": "run shell commands", "Read": "read files", "Edit": "edit files", "Write": "create / overwrite files",
              "Glob": "list files", "Grep": "search inside files", "WebFetch": "open web pages", "WebSearch": "search the web",
              "SendMessage": "message other agents", "ListAgents": "see which agents run", "Agent": "start helper sub-agents",
              "Task": "start helper sub-agents", "NotebookEdit": "edit notebooks"}
RULE_RX = re.compile(r"^[A-Za-z_][\w.-]*(\((?:[^()\n]|\([^()\n]*\)){1,400}\))?$")


def explain(rule):
    r = rule.strip(); m = re.match(r"^([A-Za-z_][\w.-]*)(?:\((.*)\))?$", r, re.S)
    if not m or not RULE_RX.match(r):
        return {"group": "Not a rule", "plain": "Free text. Claude Code ignores this line (not a tool rule).", "valid": False}
    tool, arg = m[1], m[2]
    if tool.startswith("mcp__"):
        p = tool.split("__")
        srv = p[1].replace("claude_ai_", "").replace("_", " ") if len(p) > 1 else tool
        return {"group": "Connectors", "plain": f"use all {srv} tools" if len(p) <= 2 or not p[2] else f"use {srv}: {p[2].replace('_', ' ')}", "valid": True}
    base = PLAIN_TOOL.get(tool, f"use the {tool} tool")
    grp = "Shell" if tool == "Bash" else "Files" if tool in ("Read", "Edit", "Write", "Glob", "Grep", "NotebookEdit") else \
          "Web" if tool in ("WebFetch", "WebSearch") else "Agents" if tool in ("SendMessage", "ListAgents", "Agent", "Task") else "Other"
    if not arg:
        return {"group": grp, "plain": base + " (any)", "valid": True}
    if tool == "Bash":
        a = arg[:-2] if arg.endswith(":*") else arg.rstrip("*").rstrip()
        return {"group": grp, "plain": f"run commands that start with “{a.strip()}”" if arg.endswith(("*", ":*")) else f"run exactly “{arg}”", "valid": True}
    if tool in ("Read", "Edit", "Write", "Glob", "Grep"):
        p = arg[1:] if arg.startswith("//") else arg.replace("~", HOME, 1)
        deep = p.endswith("/**"); p = p[:-3] if deep else p
        short = p.replace(HOME, "~")
        return {"group": grp, "plain": f"{base} in {short}" + (" and all sub-folders" if deep else ""), "valid": True}
    if tool == "WebFetch" and arg.startswith("domain:"):
        return {"group": grp, "plain": f"open pages on {arg[7:]}", "valid": True}
    return {"group": grp, "plain": f"{base}: {arg}", "valid": True}


def overrides_path(slug):
    return f"{AGDIR}/{slug}.settings.json"


def load_overrides(slug):
    try:
        d = json.load(open(overrides_path(slug)))
    except Exception:
        d = {}
    p = d.setdefault("permissions", {})
    for k in ("allow", "deny"):
        p[k] = [x for x in p.get(k, []) if isinstance(x, str)]
    return d


def permissions(name, cwd, card_secs):
    srcs = [(f"{HOME}/.claude/settings.json", "Your user settings · all agents"),
            (f"{HOME}/.claude/settings.local.json", "Your local settings · all agents")]
    if cwd and os.path.realpath(cwd) != os.path.realpath(HOME):
        srcs += [(f"{cwd}/.claude/settings.json", "Project settings · this agent's folder"),
                 (f"{cwd}/.claude/settings.local.json", "Project local settings · this agent's folder")]
    rules, dirs, mode, files = [], [], None, []
    for p, lab in srcs:
        try:
            d = json.load(open(p))
        except Exception:
            continue
        files.append({"path": p.replace(HOME, "~"), "label": lab})
        pm = d.get("permissions") or {}
        mode = pm.get("defaultMode") or mode
        dirs += [x for x in pm.get("additionalDirectories", []) if x not in dirs]
        for lst in ("allow", "ask", "deny"):
            for r in pm.get(lst, []) or []:
                rules.append({"rule": r, "list": lst, "src": lab, "file": p.replace(HOME, "~"), **explain(r)})
    slug = slug_of(name); ov = load_overrides(slug)
    hard = pick(card_secs, r"hard|^rules|rules \(hard\)|^limits")
    return {"rules": rules, "dirs": [x.replace(HOME, "~") for x in dirs], "defaultMode": mode, "files": files,
            "hard": {"title": hard["title"], "md": hard["md"]} if hard else None,
            "overrides": {"path": overrides_path(slug).replace(HOME, "~"), "exists": os.path.exists(overrides_path(slug)),
                          "allow": [{"rule": r, **explain(r)} for r in ov["permissions"]["allow"]],
                          "deny": [{"rule": r, **explain(r)} for r in ov["permissions"]["deny"]]},
            "log": perm_log(slug)}


def perm_log(slug, n=8):
    try:
        lines = [ln for ln in open(PERMLOG, encoding="utf-8").read().splitlines() if f" {slug} " in ln]
    except Exception:
        return []
    return lines[-n:][::-1]


def perm_change(data, srv):
    """Only from an explicit click + confirm in the UI. Writes ONLY the per-agent overrides file."""
    slug = str(data.get("slug") or ""); op = data.get("op"); lst = data.get("list"); rule = str(data.get("rule") or "").strip()
    if slug not in SLUG.values() or op not in ("add", "remove") or lst not in ("allow", "deny") or data.get("confirmed") is not True:
        return 400, {"ok": False, "error": "bad request"}
    if op == "add" and (len(rule) > 420 or not RULE_RX.match(rule)):
        return 400, {"ok": False, "error": "Not a valid rule. Use Tool or Tool(pattern), e.g. Bash(git status:*) or Read(~/Documents/**)."}
    os.makedirs(AGDIR, exist_ok=True)
    d = load_overrides(slug); L = d["permissions"][lst]
    if op == "add":
        if rule in L:
            return 200, {"ok": True, "same": True}
        other = "deny" if lst == "allow" else "allow"
        d["permissions"][other] = [x for x in d["permissions"][other] if x != rule]
        L.append(rule)
    else:
        if rule not in L:
            return 200, {"ok": True, "same": True}
        L.remove(rule)
    d.pop("_note", None)
    tmp = overrides_path(slug) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, overrides_path(slug))
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    name = name_of_slug(slug) or slug
    with open(PERMLOG, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {slug} {op} {lst} {rule}  ({HUMAN}, Officina)\n")
    srv.wake(f"[permissions] {HUMAN} {'added' if op == 'add' else 'removed'} {lst.upper()} rule for {srv.norm_agent(name) if name else slug}: {rule} "
             f"— file {overrides_path(slug).replace(HOME, '~')}; takes effect at the agent's next restart (--settings).")
    return 200, {"ok": True}


# ---------------- scores ----------------
def score(name):
    try:
        d = json.load(open(SCORES))
    except Exception:
        return None
    ag = d.get("agents") or {}
    keys = [name, name, slug_of(name)]
    s = next((ag[k] for k in keys if k in ag), None)
    if s is None:
        s = next((v for k, v in ag.items() if k.lower() in [x.lower() for x in keys]), None)
    return {**s, "updated": d.get("updated")} if isinstance(s, dict) else None


def _agent_key(d, name):
    keys = [name, name, slug_of(name)]
    for k in keys:
        if k in d:
            return d[k]
    low = {k.lower(): v for k, v in d.items()}
    return next((low[k.lower()] for k in keys if k.lower() in low), None)


def score_history(name, days=30):
    """Daily points for the profile chart (last `days` days) + the team overall lines (for the coordinator's profile)."""
    try:
        h = json.load(open(SCORES_HIST)).get("days") or {}
    except Exception:
        h = {}
    cut = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    me, team = [], {}
    for day in sorted(k for k in h if k >= cut):
        row = h[day] or {}
        s = _agent_key(row, name)
        if isinstance(s, dict) and s.get("overall") is not None:
            mets = {k: (v.get("score") if isinstance(v, dict) else v) for k, v in (s.get("metrics") or {}).items()}
            ev = {k: v.get("evidence") for k, v in (s.get("metrics") or {}).items() if isinstance(v, dict) and v.get("evidence")}
            me.append({"day": day, "overall": s.get("overall"), "metrics": mets, "evidence": ev, "tips": s.get("tips") or [],
                       "formula": s.get("formula"), "peers": s.get("peers"), "human": s.get("human")})
        if name == COORD:
            for k, v in row.items():
                if isinstance(v, dict) and v.get("overall") is not None:
                    team.setdefault(k, []).append({"day": day, "overall": v["overall"]})
    return {"points": me, "team": team if name == COORD else None, "today": datetime.date.today().isoformat()}


def _needs_of(name):
    """Tech's grouped needs/proposals for this agent: scores.json top-level "needs" (keyed by agent) or agents.<n>.needs."""
    try:
        d = json.load(open(SCORES))
    except Exception:
        return None
    n = d.get("needs")
    if isinstance(n, dict):
        v = _agent_key(n, name)
        if v:
            return v
    elif isinstance(n, list):
        keys = {x.lower() for x in (name, name, slug_of(name))}
        v = [x for x in n if isinstance(x, dict) and str(x.get("agent") or x.get("for") or "").lower() in keys]
        if v:
            return v
    s = _agent_key(d.get("agents") or {}, name)
    return s.get("needs") if isinstance(s, dict) else None


def feedback(name, days=7):
    """Peer + human notes about this agent from votes/<day>/<voter>.json, newest first. Old {"score","why"} -> why = helped."""
    keys = {name, name, slug_of(name)}
    low = {k.lower() for k in keys}
    out = []
    for i in range(days):
        day = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
        for f in sorted(glob.glob(f"{VOTES}/{day}/*.json")):
            voter = os.path.basename(f)[:-5]
            if voter.lower() in low:
                continue
            try:
                d = json.load(open(f))
            except Exception:
                continue
            v = next((d[k] for k in d if k.lower() in low), None) if isinstance(d, dict) else None
            if not isinstance(v, dict):
                continue
            helped = str(v.get("helped") or v.get("why") or "").strip()
            needs = str(v.get("needs") or "").strip()
            out.append({"voter": voter, "day": day, "score": v.get("score"), "helped": helped[:300], "needs": needs[:300], "at": v.get("at")})
    return out[:40]


# ---------------- the human's daily vote (board vote: 50 % formula · 30 % peers · 20 % human) ----------------
VOTES = f"{OFFICE}/votes"


def my_vote(name):
    p = f"{VOTES}/{datetime.date.today().isoformat()}/{HUMAN}.json"
    try:
        d = json.load(open(p))
    except Exception:
        return None
    v = d.get(name)
    return v if isinstance(v, dict) else None


def vote(data, srv):
    """The human rates one agent 1-10 for today (overwrites the earlier vote for that agent today). Only from a click in the UI."""
    name = srv.norm_agent(str(data.get("name") or ""))
    try:
        sc = int(data.get("score"))
    except Exception:
        sc = 0
    if name not in SLUG or not 1 <= sc <= 10:
        return 400, {"ok": False, "error": "bad request"}
    clean = lambda k: re.sub(r"\s+", " ", str(data.get(k) or "")).strip()[:300]
    helped, needs = clean("helped") or clean("why"), clean("needs")
    day = datetime.date.today().isoformat(); os.makedirs(f"{VOTES}/{day}", exist_ok=True)
    p = f"{VOTES}/{day}/{HUMAN}.json"
    try:
        d = json.load(open(p))
    except Exception:
        d = {}
    key = name
    d[key] = {"score": sc, "helped": helped, "needs": needs, "at": datetime.datetime.now().strftime("%H:%M")}
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)
    return 200, {"ok": True, "vote": d[key]}


# ---------------- session facts ----------------
def session_info(name, srv):
    best = None
    for f in glob.glob(f"{HOME}/.claude/sessions/*.json"):
        try:
            d = json.load(open(f)); os.kill(int(d["pid"]), 0)
        except Exception:
            continue
        if srv.norm_agent(d.get("name") or "") == name or (name == COORD and (d.get("name") or "").startswith(COORD)):
            if not best or d.get("updatedAt", 0) > best.get("updatedAt", 0):
                best = d
    return best


NAMECACHE = {}


def tx_name(p):
    """Agent name of a transcript = its last 'agent-name' record (tail read, cached by mtime)."""
    mt = os.path.getmtime(p); c = NAMECACHE.get(p)
    if c and c[0] == mt:
        return c[1]
    nm = None
    try:
        with open(p, "rb") as f:
            sz = os.path.getsize(p)
            for start, n in ((max(0, sz - 300_000), 300_000), (0, 300_000)):
                f.seek(start); hits = re.findall(rb'"type":"agent-name","agentName":"([^"]+)"', f.read(n))
                if hits:
                    nm = hits[-1].decode("utf-8", "replace"); break
    except Exception:
        pass
    NAMECACHE[p] = (mt, nm)
    return nm


def transcripts(name, sess, srv):
    """Every transcript of this agent touched in the last 7 days (sessions are cleared / restarted often)."""
    now = time.time(); dirs = {S.PROJECTS}
    if sess and sess.get("cwd"):
        dirs.add(f"{HOME}/.claude/projects/{re.sub(r'[^A-Za-z0-9]', '-', sess['cwd'])}")
    ps = []
    for d in dirs:
        for p in glob.glob(f"{d}/*.jsonl"):
            try:
                if now - os.path.getmtime(p) < 7 * DAY and srv.norm_agent(re.sub(r"\s*\(\d+\)$", "", tx_name(p) or "")) == name:
                    ps.append(p)
            except Exception:
                pass
    if sess:
        tp = f"{HOME}/.claude/projects/{re.sub(r'[^A-Za-z0-9]', '-', sess.get('cwd', HOME))}/{sess.get('sessionId')}.jsonl"
        if os.path.exists(tp) and tp not in ps:
            ps.append(tp)
    if name == COORD:
        cur = srv.CHAT.transcript()
        if cur and cur not in ps:
            ps.append(cur)
    ps.sort(key=os.path.getmtime)
    return ps[-6:]


def open_items(name, srv, card_secs):
    lab = (name.lower(),)
    tasks = [t for t in srv.jload("tasks.json", []) if str(t.get("owner", "")).lower() in lab and t.get("state") != "done"]
    cards = [c for c in srv.jload("cards.json", []) if str(c.get("from", "")).lower() in lab and c.get("state") == "open"]
    oi = pick(card_secs, r"open items")
    return {"tasks": tasks, "cards": cards, "card": oi}


def profile(name, srv):
    name = srv.norm_agent(name)
    if name not in SLUG and name not in srv.ORDER:
        return {"ok": False, "error": "unknown agent"}
    card = role_card(name); secs = md_sections(card["text"])
    sess = session_info(name, srv)
    tm = next((a for a in srv.team() if a["name"] == name), {}) or {}
    tps = transcripts(name, sess, srv)
    snaps = [scan_for(p, srv).snapshot() for p in tps]
    tx = merge(snaps) if snaps else {"ready": True, "model": None, "mode": None, "first": None, "tools": [], "mcp": [], "day": [0] * 144,
                                     "week": [0] * 168, "steps": [], "msgs": [], "helpers": [], "helperTotal": 0, "files": []}
    files = tx.pop("files", [])
    ev = [e for tr in srv.tracks() for e in tr.events if name in (e["from"], e["to"]) and e["from"] != e["to"]]
    live_msgs = [{"ts": e["ts"], "dir": "out" if e["from"] == name else "in", "peer": e["to"] if e["from"] == name else e["from"], "text": e["summary"]} for e in ev]
    seen = {(round(m["ts"]), m["dir"]) for m in tx["msgs"]}
    msgs = sorted(tx["msgs"] + [m for m in live_msgs if (round(m["ts"]), m["dir"]) not in seen], key=lambda m: -m["ts"])[:20]
    tmux = (sess or {}).get("tmux") or ""
    return {"ok": True, "name": name, "label": name, "slug": slug_of(name),
            "role": ROLE_LINE.get(name, "agent"), "color": srv.COLORS.get(name, "#8a8478"),
            "state": tm.get("state", "offline"), "live": tm.get("live", ""), "doing": tm.get("doing", ""), "needs": tm.get("needs", ""),
            "where": tm.get("where", ""), "age": tm.get("age"),
            "session": {"started": int(sess["startedAt"] / 1000) if sess and sess.get("startedAt") else None,
                        "tmux": tmux.split(":")[0] if tmux else (TMUX.get(name, slug_of(name)) if tm.get("where") == "background" else ""),
                        "id": (sess or {}).get("sessionId"), "cwd": ((sess or {}).get("cwd") or "").replace(HOME, "~"), "version": (sess or {}).get("version"),
                        "ctx": srv.ctx_tokens(tps[-1]) if tps else None, "current": os.path.basename(tps[-1])[:8] if tps else None, "model": tx.get("model"), "mode": tx.get("mode"),
                        "transcripts": len(tps)},
            "card": {"path": card["path"].replace(HOME, "~"), "exists": bool(card["text"]), "md": card["text"], "mtime": card["mtime"]},
            "personas": personas(secs), "subcard": pick(secs, r"sub-?agents|helpers"),
            "notes": notes(name), "memory": memory_links(name, card["text"]),
            "running": srv.subagents(fresh=False).get(name, []), "tx": tx, "msgs": msgs,
            "score": score(name), "hist": score_history(name), "myVote": my_vote(name), "feedback": feedback(name), "techNeeds": _needs_of(name), "perm": permissions(name, (sess or {}).get("cwd"), secs),
            "deliver": deliverables(name, files, srv), "open": open_items(name, srv, secs)}
