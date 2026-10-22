"""Officina — a local office around a team of Claude Code agents (http://localhost:<port>, see config.json).

Shows (read):   chat = the coordinator's Claude Code conversation (jsonl transcript, read incrementally)
                ~/.claude/status/*.txt      team heartbeat + silence watchdog (agent-status.sh)
                <office>/*.json             tasks, cards, artifacts, routines, summary
                <office>/log/*.md           daily log
                <office>/file-moves.md      file activity (optional)
Writes:         <office>/wake.txt           chat input / card answers / events → the coordinator's watcher
                <office>/tasks.json, cards.json (from the UI)
Agent tabs: read-only tail of each live peer session (~/.claude/sessions/*.json → its transcript).
Never starts or controls agents itself; the coordinator does that from its session.
All names, paths and the port come from settings.py / config.json.
"""
import json, os, re, time, subprocess, datetime, threading, glob
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import sys
import profile_api   # agent profile page
import flow          # flow lanes + stuck alarm (pushes only if flow/config.json push=true and a push_script is set)

from settings import (HOME, OFFICE, STATUS, WAKE, COLORS, ORDER, COORD, HUMAN, PROJECTS, SESSIONS, PORT, TAILNET_IP,
                      TIMELINE, LOCATION, CACHE, ROOTS, TOOLS, VENV_PY, which, render)
from settings import FILE_LOG as LOG
HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(f"{OFFICE}/log", exist_ok=True)
STATES = ["doing", "in review", "blocked", "waiting", "done"]   # waiting = on the human


def jload(name, default):
    try:
        return json.load(open(f"{OFFICE}/{name}"))
    except Exception:
        return default


def jsave(name, data):
    tmp = f"{OFFICE}/{name}.tmp"; json.dump(data, open(tmp, "w"), indent=1); os.replace(tmp, f"{OFFICE}/{name}")


def wake(text):
    """Hand text to the coordinator's watcher (wake file). Appends, so quick answers are never lost."""
    with WAKE_LOCK:
        with open(WAKE + ".tmp", "w") as f:
            old = open(WAKE).read() if os.path.exists(WAKE) else ""
            f.write(old + text.strip() + "\n")
        os.replace(WAKE + ".tmp", WAKE)


WAKE_LOCK = threading.Lock()


# ---------- chat: incremental reader of the coordinator's transcript ----------
class Chat:
    def __init__(self):
        self.lock = threading.Lock(); self.msgs = []; self.path = None; self.off = 0

    def transcript(self):
        # the coordinator's live conversation can change (restart, background session): newest live session with its name wins.
        live = []
        for f in glob.glob(f"{HOME}/.claude/sessions/*.json"):
            try:
                d = json.load(open(f)); os.kill(int(d["pid"]), 0)
            except Exception:
                continue
            tp = f"{PROJECTS}/{d.get('sessionId')}.jsonl"
            if (d.get("name") or "").startswith(COORD) and os.path.exists(tp):
                live.append(tp)
        if live:
            return max(live, key=os.path.getmtime)
        cfg = jload("config.json", {})
        p = cfg.get("coordinator_transcript")
        if p and os.path.exists(p):
            return p
        files = sorted(glob.glob(f"{PROJECTS}/*.jsonl"), key=os.path.getmtime, reverse=True)
        return files[0] if files else None

    @staticmethod
    def clean_user(t):
        t = re.sub(r"<system-reminder>[\s\S]*?</system-reminder>", "", t)
        t = re.sub(r"<(command-[a-z]+|local-command-[a-z]+|bash-[a-z]+)>[\s\S]*?</\1>", "", t)
        return t.strip()

    def parse(self, line):
        try:
            d = json.loads(line)
        except Exception:
            return None
        if d.get("isMeta") or d.get("isSidechain"):
            return None
        ts = (d.get("timestamp") or "")[:19].replace("T", " ")
        m = d.get("message") or {}
        if d.get("type") == "user":
            c = m.get("content")
            if isinstance(c, str):
                if "<cross-session-message" in c or "<agent-message" in c:
                    frm = re.search(r'from-name="([^"]+)"', c)
                    body = re.search(r"<(?:cross-session-message|agent-message)[^>]*>([\s\S]*?)</(?:cross-session-message|agent-message)>", c)
                    txt = (body[1] if body else re.sub(r"<[^>]+>", "", c)).strip()
                    return {"who": "agent", "name": frm[1] if frm else "subagent", "text": txt[:1500], "ts": ts}
                if re.match(r"\s*<(task-notification|cross-session-message|agent-message|system-reminder|local-command-caveat)", c):
                    if "<cross-session-message" in c:
                        frm = re.search(r'from-name="([^"]+)"', c); body = re.sub(r"<[^>]+>", "", c).strip()
                        return {"who": "agent", "name": frm[1] if frm else "agent", "text": body[:1200], "ts": ts}
                    return None
                t = self.clean_user(c)
                return {"who": "human", "text": t, "ts": ts} if t else None
            if isinstance(c, list):
                for p in c:
                    if p.get("type") == "tool_result":
                        r = p.get("content"); r = r if isinstance(r, str) else " ".join(x.get("text", "") for x in r if isinstance(x, dict))
                        mm = re.search(re.escape(HUMAN) + r" said:\s*\n([\s\S]+?)(\n\[exited|\Z)", r or "")
                        if mm:
                            return {"who": "human", "text": mm[1].strip(), "ts": ts, "via": "voice/office"}
                        mv = re.search(r"Voice response: ([\s\S]+?) \(STT:", r or "")
                        if mv:
                            return {"who": "human", "text": mv[1].strip(), "ts": ts, "via": "voice"}
                    if p.get("type") == "text" and p.get("text", "").strip():
                        t = self.clean_user(p["text"])
                        if t and not t.startswith("[Request interrupted"):
                            return {"who": "human", "text": t, "ts": ts}
            return None
        if d.get("type") == "assistant":
            parts = [p.get("text", "") for p in (m.get("content") or []) if isinstance(p, dict) and p.get("type") == "text"]
            t = "\n".join(x for x in parts if x.strip()).strip()
            return {"who": "coord", "text": t, "ts": ts} if t else None
        return None

    def update(self):
        """Read every coordinator transcript in order (config coordinator_history), so the archive survives restarts."""
        with self.lock:
            p = self.transcript()
            if not p:
                return
            cfg = jload("config.json", {}); hist = cfg.get("coordinator_history") or ([cfg["coordinator_transcript"]] if cfg.get("coordinator_transcript") else [])
            if p not in hist:
                hist.append(p); cfg["coordinator_history"] = hist; cfg["coordinator_transcript"] = p; jsave("config.json", cfg)
            if not isinstance(self.off, dict) or self.path != hist[:]:
                if not (isinstance(self.off, dict) and self.path == hist[:len(self.path)]):
                    self.off, self.msgs = {}, []
                self.path = hist[:]
            for tp in hist:
                if not os.path.exists(tp):
                    continue
                size, off = os.path.getsize(tp), self.off.get(tp, 0)
                if size <= off:
                    continue
                with open(tp, "rb") as f:
                    f.seek(off); chunk = f.read(); last_nl = chunk.rfind(b"\n")
                if last_nl < 0:
                    continue
                self.off[tp] = off + last_nl + 1
                for line in chunk[:last_nl].split(b"\n"):
                    msg = self.parse(line.decode("utf-8", "replace"))
                    if msg:
                        if self.msgs and self.msgs[-1]["who"] == msg["who"] == "coord" and self.msgs[-1]["ts"][:16] == msg["ts"][:16]:
                            self.msgs[-1]["text"] += "\n\n" + msg["text"]
                        else:
                            self.msgs.append(msg)

    def get(self, before=None, n=120):
        self.update()
        with self.lock:
            idx = len(self.msgs) if before is None else max(0, min(before, len(self.msgs)))
            start = max(0, idx - n)
            return {"messages": self.msgs[start:idx], "start": start, "total": len(self.msgs)}


CHAT = Chat()
threading.Thread(target=CHAT.update, daemon=True).start()   # warm the cache at startup


# ---------- agent tabs: live, read-only feed of each peer session (tail of its transcript) ----------
SESS = f"{HOME}/.claude/sessions"
TAIL = 4 * 1024 * 1024          # first read: last 4 MB only (transcripts are hundreds of MB)


def tool_line(p):
    n = p.get("name", "tool"); i = p.get("input") or {}
    d = i.get("description") or i.get("command") or i.get("file_path") or i.get("pattern") or i.get("prompt") or i.get("query") \
        or i.get("message") or i.get("to") or i.get("url") or ""
    if n == "SendMessage":
        d = f"→ {i.get('to', '')}: {(i.get('message') or '').splitlines()[0] if i.get('message') else ''}"
    if n.startswith("mcp__"):
        n = n.split("__", 2)[-1]
    return {"who": "tool", "tool": n, "text": str(d).replace("\n", " ")[:220]}


class Feed:
    def __init__(self, path):
        self.lock = threading.Lock(); self.path = path; self.msgs = []; self.off = max(0, os.path.getsize(path) - TAIL); self.first = True

    def update(self):
        with self.lock:
            size = os.path.getsize(self.path)
            if size <= self.off:
                return
            with open(self.path, "rb") as f:
                f.seek(self.off); chunk = f.read()
            if self.first:                                   # drop the partial first line of the tail
                chunk = chunk[chunk.find(b"\n") + 1:] if self.off else chunk; self.off = size - len(chunk); self.first = False
            last_nl = chunk.rfind(b"\n")
            if last_nl < 0:
                return
            self.off += last_nl + 1
            for line in chunk[:last_nl].split(b"\n"):
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("isSidechain"):
                    continue
                ts = (d.get("timestamp") or "")[11:16]
                if d.get("type") == "assistant":
                    for c in (d.get("message") or {}).get("content") or []:
                        if c.get("type") == "tool_use":
                            self.msgs.append({**tool_line(c), "ts": ts})
                        elif c.get("type") == "text" and c.get("text", "").strip():
                            self.msgs.append({"who": "agent", "text": c["text"].strip(), "ts": ts})
                else:
                    m = CHAT.parse(line.decode("utf-8", "replace"))
                    if m:
                        m["ts"] = ts; self.msgs.append(m)
            self.msgs = self.msgs[-400:]

    def get(self, since=0):
        self.update()
        with self.lock:
            return {"messages": self.msgs[-250:], "total": len(self.msgs)}


FEEDS = {}


def sessions():
    out = []
    for f in glob.glob(f"{SESS}/*.json"):
        try:
            d = json.load(open(f)); os.kill(int(d["pid"]), 0)
        except Exception:
            continue
        name = d.get("name") or f"session {d.get('pid')}"
        if name.startswith(COORD):
            name = COORD
        tp = f"{HOME}/.claude/projects/{re.sub(r'[^A-Za-z0-9]', '-', d.get('cwd', HOME))}/{d.get('sessionId')}.jsonl"
        out.append({"name": name, "label": name, "status": d.get("status", "?"),
                    "color": COLORS.get(name, "#8a8478"), "transcript": tp if os.path.exists(tp) else None, "tmux": bool(d.get("tmux"))})
    try:                                                     # agents in tmux that have not registered yet (e.g. trust question)
        live = subprocess.run([which("tmux"), "ls", "-F", "#S"], capture_output=True, text=True, timeout=2).stdout.split()
    except Exception:
        live = []
    for name in ORDER[1:]:
        slug = name.lower().replace(" ", "-")
        if slug in live:
            a = next((x for x in out if x["name"] == name), None)
            if a:
                a["tmux"] = True
            else:
                out.append({"name": name, "label": name, "status": "starting", "color": COLORS.get(name, "#8a8478"), "transcript": None, "tmux": True})
    out.sort(key=lambda a: ORDER.index(a["name"]) if a["name"] in ORDER else 99)
    return out


def agent_feed(name):
    a = next((x for x in sessions() if x["name"] == name), None)
    if not a or not a["transcript"]:
        return {"messages": [], "total": 0, "status": "offline"}
    fd = FEEDS.get(name)
    if not fd or fd.path != a["transcript"]:
        fd = FEEDS[name] = Feed(a["transcript"])
    return {**fd.get(), "status": a["status"]}


# ---------- comms + sub-agents: who messages whom, who runs helpers (from live transcripts, read-only) ----------
CTAIL = 6 * 1024 * 1024
CMARK = (b"SendMessage", b'"Agent"', b'"Task"', b"task-notification", b"end_turn")
SUBSTALE = 30 * 60                                   # background helper whose own transcript is quiet this long = gone


def norm_agent(n):
    n = (n or "").strip()
    if n.lower().startswith(COORD.lower()):
        return COORD
    if n.lower() in (HUMAN.lower(), "user"):
        return HUMAN
    return n


def iso_ts(s):
    try:
        return datetime.datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


class Track:
    """Incremental scan of one live transcript: SendMessage events, human <-> coordinator turns, Agent/Task helpers."""
    def __init__(self, path, who):
        self.lock = threading.Lock(); self.path, self.who = path, who
        self.off = max(0, os.path.getsize(path) - CTAIL); self.first = True
        self.events, self.subs, self.done, self.aids, self.seen = [], {}, set(), {}, set()

    def ev(self, eid, ts, frm, to, summary, sub=None):
        if eid in self.seen:
            return
        self.seen.add(eid)
        self.events.append({"id": eid, "ts": ts, "from": frm, "to": to, "summary": (summary or "").strip()[:140], **({"sub": sub} if sub else {})})

    def line(self, raw):
        pend = [k.encode() for k in self.subs if k not in self.done]
        if not (any(m in raw for m in CMARK) or (self.who == COORD and b'"type":"user"' in raw) or any(p in raw for p in pend)):
            return
        try:
            d = json.loads(raw)
        except Exception:
            return
        t = d.get("type")
        if t not in ("assistant", "user", "queue-operation", "attachment") or d.get("isSidechain"):
            return
        ts = iso_ts(d.get("timestamp")); m = d.get("message") or {}
        if t == "assistant":
            texts = []
            for c in m.get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and c.get("text", "").strip():
                    texts.append(c["text"].strip())
                if c.get("type") != "tool_use":
                    continue
                i = c.get("input") or {}
                if c.get("name") == "SendMessage":
                    to = str(i.get("to") or i.get("recipient") or "")
                    summ = i.get("summary") or (str(i.get("message") or "").strip().splitlines() or [""])[0]
                    if to in self.aids:                                  # message to one of its own helpers
                        self.ev(c["id"], ts, self.who, self.who, summ, sub=self.aids[to])
                    elif to == "*":
                        self.ev(c["id"], ts, self.who, "*", summ)
                    elif not re.fullmatch(r"a[0-9a-f]{12,}", to):
                        self.ev(c["id"], ts, self.who, norm_agent(to), summ)
                elif c.get("name") in ("Agent", "Task"):
                    self.subs[c["id"]] = {"id": c["id"], "desc": str(i.get("description") or i.get("subagent_type") or "helper")[:80],
                                          "type": i.get("subagent_type") or "", "since": ts, "bg": bool(i.get("run_in_background")), "aid": None}
            if self.who == COORD and m.get("stop_reason") == "end_turn" and texts:
                self.ev(d.get("uuid") or f"k{ts}", ts, COORD, HUMAN, texts[-1].splitlines()[0])
            return
        txt = raw.decode("utf-8", "replace")
        if "task-notification" in txt:                                 # background helper finished / stopped
            for b in re.finditer(r"<task-notification>(.*?)</task-notification>", txt, re.S):
                tid, st = re.search(r"<tool-use-id>(toolu_\w+)</tool-use-id>", b[1]), re.search(r"<status>(\w+)</status>", b[1])
                if tid and st and st[1] != "running":
                    self.done.add(tid[1])
        if t != "user":
            return
        c = m.get("content")
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "tool_result" and p.get("tool_use_id") in self.subs:
                    s = self.subs[p["tool_use_id"]]; r = p.get("content")
                    r = r if isinstance(r, str) else " ".join(x.get("text", "") for x in r or [] if isinstance(x, dict))
                    if "Async agent launched" in r or "agentId:" in r and "async" in r.lower():
                        s["bg"] = True; a = re.search(r"agentId:\s*(\w+)", r)
                        if a:
                            s["aid"] = a[1]; self.aids[a[1]] = s["id"]
                    else:
                        self.done.add(s["id"])                         # foreground helper returned (or failed)
        if self.who == COORD:
            msg = CHAT.parse(txt)
            if msg and msg.get("who") == "human":
                self.ev(d.get("uuid") or f"e{ts}", ts, HUMAN, COORD, msg["text"].splitlines()[0] if msg["text"] else "")

    def update(self):
        with self.lock:
            size = os.path.getsize(self.path)
            if size <= self.off:
                return
            with open(self.path, "rb") as f:
                f.seek(self.off); chunk = f.read()
            if self.first:
                chunk = chunk[chunk.find(b"\n") + 1:] if self.off else chunk; self.off = size - len(chunk); self.first = False
            last_nl = chunk.rfind(b"\n")
            if last_nl < 0:
                return
            self.off += last_nl + 1
            for raw in chunk[:last_nl].split(b"\n"):
                self.line(raw)
            self.events = self.events[-200:]

    def running(self):
        now, out = time.time(), []
        for s in self.subs.values():
            if s["id"] in self.done or now - s["since"] > 8 * 3600:
                continue
            if s["bg"] and s["aid"]:
                f = f"{os.path.splitext(self.path)[0]}/subagents/agent-{s['aid']}.jsonl"
                if os.path.exists(f) and now - os.path.getmtime(f) > SUBSTALE:
                    continue
            out.append({"id": s["id"], "desc": s["desc"], "type": s["type"], "since": int(s["since"])})
        return out


TRACKS, TLOCK = {}, threading.Lock()


def tracks():
    out = []
    with TLOCK:
        for a in sessions():
            tp = a.get("transcript")
            if not tp:
                continue
            tr = TRACKS.get(tp)
            if not tr:
                tr = TRACKS[tp] = Track(tp, a["name"])
            out.append(tr)
    for tr in out:
        try:
            tr.update()
        except Exception:
            pass
    return out


def comms(since=0.0):
    now = time.time(); lo = max(since, now - 300)
    ev = [e for tr in tracks() for e in tr.events if e["ts"] > lo]
    ev.sort(key=lambda e: e["ts"])
    return {"now": now, "events": ev, "subagents": subagents(fresh=False)}


def ctx_tokens(tp):
    """Context size of a session = tokens of its last main-thread API call (tail read, cheap)."""
    try:
        with open(tp, "rb") as f:
            f.seek(max(0, os.path.getsize(tp) - 400_000)); chunk = f.read()
        for raw in reversed(chunk.split(b"\n")):
            if b'"usage"' not in raw or b'"assistant"' not in raw:
                continue
            d = json.loads(raw)
            if d.get("type") != "assistant" or d.get("isSidechain"):
                continue
            u = (d.get("message") or {}).get("usage") or {}
            n = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0)
            if n:
                return n
    except Exception:
        pass
    return None


def agent_card(name):
    """Hover card data for one team member: status, recent steps, helpers, last messages, context size."""
    name = norm_agent(name) if name else name
    tm = next((a for a in team() if a["name"] == name), None) or {"name": name, "label": name}
    feed = agent_feed(name) if name != COORD else None
    if name == COORD:
        t = CHAT.transcript(); fd = FEEDS.get("__coord")
        if t and (not fd or fd.path != t):
            fd = FEEDS["__coord"] = Feed(t)
        feed = fd.get() if fd else {"messages": []}
    msgs = (feed or {}).get("messages") or []
    steps = [m for m in msgs if m.get("who") == "tool"][-3:]
    says = [m for m in msgs if m.get("who") in ("agent", "coord")][-1:]
    ev = [e for tr in tracks() for e in tr.events if name in (e["from"], e["to"])]
    ev.sort(key=lambda e: e["ts"])
    out_ev = next((e for e in reversed(ev) if e["from"] == name and e["to"] != name), None)
    in_ev = next((e for e in reversed(ev) if e["to"] == name and e["from"] != name), None)
    s = next((a for a in sessions() if a["name"] == name), None)
    tp = CHAT.transcript() if name == COORD else (s and s.get("transcript"))
    helpers = {aid: tr.subs[tid]["desc"] for tr in TRACKS.values() for aid, tid in tr.aids.items() if tid in tr.subs}
    steps = [{**m, "text": re.sub(r"→ (a[0-9a-f]{12,})", lambda x: "→ helper " + helpers.get(x[1], ""), m.get("text", ""))} for m in steps]
    last = int(time.time() - os.path.getmtime(tp)) if tp and os.path.exists(tp) else None
    return {"name": name, "label": tm.get("label", name), "state": tm.get("state", "offline"), "live": tm.get("live", ""),
            "doing": tm.get("doing", ""), "needs": tm.get("needs", ""), "where": tm.get("where", ""), "age": tm.get("age"),
            "steps": [{"tool": m.get("tool"), "text": m.get("text", "")[:140], "ts": m.get("ts", "")} for m in steps],
            "said": [{"text": m.get("text", "")[:400], "ts": m.get("ts", "")} for m in says],
            "out": out_ev, "in": in_ev, "subs": subagents(fresh=False).get(name, []),
            "ctx": ctx_tokens(tp) if tp else None, "quiet": last}


def subagents(fresh=True):
    out = {}
    for tr in (tracks() if fresh else [t for t in TRACKS.values()]):
        if fresh is False and not os.path.exists(tr.path):
            continue
        r = tr.running()
        if r:
            out.setdefault(tr.who, []).extend(r)
    for k in out:
        out[k].sort(key=lambda s: s["since"])
    return out


# ---------- artifacts viewer: an agent (office.sh view) or the UI opens a file inside the app ----------
IFCPY = VENV_PY                                              # venv with IfcOpenShell + rhino3dm (install.sh)
KINDS = {".pdf": "pdf", ".png": "img", ".jpg": "img", ".jpeg": "img", ".gif": "img", ".webp": "img", ".svg": "img",
         ".ifc": "ifc", ".glb": "glb", ".stp": "step", ".step": "step", ".3dm": "3dm", ".md": "md", ".txt": "txt", ".csv": "txt", ".html": "html", ".mp4": "video", ".mov": "video"}
VLOCK = threading.Lock()
RQLOCK = threading.Lock()   # requests.json: agents append via office.sh, the human replies here


def rq_update(rid, fn):
    """re-read requests.json, change one item, save; returns the item or None"""
    with RQLOCK:
        d = jload("requests.json", [])
        it = next((r for r in d if str(r.get("id")) == str(rid)), None)
        if it is None:
            return None
        fn(it); jsave("requests.json", d); return it


def allowed(p):
    p = os.path.realpath(p or "")
    return p if p.startswith(ROOTS) and os.path.isfile(p) else None


def vload():
    return jload("view.json", {"items": [], "current": None, "auto": True})


def vset(fn):
    with VLOCK:
        v = vload(); fn(v); jsave("view.json", v); return v


def convert(item_id, path):
    import hashlib
    ver = "3dm-1" if path.lower().endswith(".3dm") else ""                     # bump to rebuild cached 3dm meshes
    out = f"{CACHE}/{hashlib.sha1(f'{path}{os.path.getmtime(path)}{ver}'.encode()).hexdigest()[:16]}.glb"
    ok = os.path.exists(out)
    if not ok:
        low = path.lower()
        cmd = ([IFCPY, f"{TOOLS}/ifc2glb.py", path, out] if low.endswith(".ifc")
               else [IFCPY, "-I", f"{TOOLS}/3dm2glb.py", path, out] if low.endswith(".3dm")   # rhino3dm, Breps meshed here
               else [which("node"), f"{TOOLS}/step2glb.js", path, out])          # .stp / .step
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=TOOLS)
        ok = r.returncode == 0 and os.path.exists(out)
    def upd(v):
        for it in v["items"]:
            if it["id"] == item_id:
                it.update({"state": "ready", "glb": out} if ok else {"state": "error"})
    vset(upd)


def pdf_info(p):
    r = subprocess.run([which("pdfinfo"), "-f", "1", "-l", "9999", p], capture_output=True, text=True, timeout=20).stdout
    return [{"w": float(m[1]), "h": float(m[2])} for m in re.finditer(r"Page\s+\d+ size:\s+([\d.]+) x ([\d.]+)", r)]


def pdf_revs(p):
    """Other revisions of a PDF: same name without YYMMDD / REV##, in its folder, its _superseded folder, or the parent of _superseded."""
    key = lambda n: re.sub(r"\s+", " ", re.sub(r"(?i)\s*REV\s*\d+", "", re.sub(r"^\d{6}\s+", "", os.path.splitext(n)[0]))).strip().lower()
    rev = lambda n: int((re.search(r"(?i)REV\s*(\d+)", n) or [0, 0])[1])
    d = os.path.dirname(p); k = key(os.path.basename(p)); dirs = [d, os.path.join(d, "_superseded")]
    if os.path.basename(d) == "_superseded":
        dirs.append(os.path.dirname(d))
    out = []
    for dd in dirs:
        try:
            for n in os.listdir(dd):
                f = os.path.join(dd, n)
                if n.lower().endswith(".pdf") and f != p and key(n) == k and os.path.isfile(f):
                    out.append({"path": f, "name": n, "rev": rev(n)})
        except OSError:
            pass
    return sorted(out, key=lambda x: -x["rev"])


def pdf_page(p, n, dpi):
    import hashlib
    dpi = max(36, min(600, int(dpi) // 12 * 12))
    out = f"{CACHE}/{hashlib.sha1(f'{p}{os.path.getmtime(p)}'.encode()).hexdigest()[:16]}-{n}-{dpi}"
    if not os.path.exists(out + ".png"):
        subprocess.run([which("pdftoppm"), "-png", "-r", str(dpi), "-f", str(n), "-l", str(n), "-singlefile", p, out], timeout=120)
    return out + ".png"


# ---------- PDF markup: the human draws boxes + comments on a PDF; "send" hands the coordinator a report with crops ----------
MARK = f"{OFFICE}/markups"; os.makedirs(MARK, exist_ok=True)


def mfile(p):
    import hashlib
    return f"{MARK}/{hashlib.sha1(p.encode()).hexdigest()[:16]}.json"


def mload(p):
    try:
        return json.load(open(mfile(p)))
    except Exception:
        return {"path": p, "items": []}


def msave(p, d):
    d["path"] = p; tmp = mfile(p) + ".tmp"; json.dump(d, open(tmp, "w"), indent=1); os.replace(tmp, mfile(p))


def msend(p, note=""):
    d = mload(p); items = [i for i in d["items"] if i.get("state") != "sent"]
    if not items:
        return None
    sizes = pdf_info(p); stamp = datetime.datetime.now().strftime("%y%m%d-%H%M"); dpi = 110
    base = os.path.splitext(os.path.basename(p))[0]; out_dir = f"{MARK}/{stamp} {base}"[:200]; os.makedirs(out_dir, exist_ok=True)
    lines = [f"# Markup — {base}", f"PDF: {p}", f"Sent: {stamp}" + (f" · note: {note}" if note else ""), ""]
    for i in items:
        pg = pdf_page(p, i["page"], dpi); sz = sizes[i["page"] - 1]; W, H = sz["w"] * dpi / 72, sz["h"] * dpi / 72
        pad = 0.03
        x0, y0 = max(0, i["x"] - pad) * W, max(0, i["y"] - pad) * H
        x1, y1 = min(1, i["x"] + i["w"] + pad) * W, min(1, i["y"] + i["h"] + pad) * H
        crop = f"{out_dir}/{i['n']:02d} p{i['page']}.png"
        subprocess.run(["/usr/bin/sips", "-c", str(int(y1 - y0)), str(int(x1 - x0)), "--cropOffset", str(int(y0)), str(int(x0)), pg, "--out", crop],
                       capture_output=True, timeout=30)
        lines += [f"## {i['n']}. page {i['page']}", i.get("text", "").strip() or "(no comment)", f"crop: {crop}",
                  f"box (page fraction): x {i['x']:.3f} y {i['y']:.3f} w {i['w']:.3f} h {i['h']:.3f}", ""]
        i["state"] = "sent"; i["sentAt"] = stamp
    open(f"{out_dir}/markup.md", "w").write("\n".join(lines)); msave(p, d)
    wake(f"[markup] {HUMAN} marked up {base}: {len(items)} comment(s). Report: {out_dir}/markup.md — check, then tell the author what to fix.")
    return {"ok": True, "count": len(items), "report": f"{out_dir}/markup.md"}


# ---------- 3D element comments (viewer.html): pin on an element + text; "send" hands the coordinator a report with snapshots ----------
C3SHOTS = f"{MARK}/3d-shots"; os.makedirs(C3SHOTS, exist_ok=True)


def c3file(p):
    import hashlib
    return f"{MARK}/{hashlib.sha1(('3d:' + p).encode()).hexdigest()[:16]}-3d.json"


def c3_load(p):
    try:
        return json.load(open(c3file(p)))
    except Exception:
        return {"path": p, "items": []}


def c3_save(p, d):
    d["path"] = p; tmp = c3file(p) + ".tmp"; json.dump(d, open(tmp, "w"), indent=1); os.replace(tmp, c3file(p))


def png_from_dataurl(u, out):
    import base64
    m = re.match(r"data:image/(png|jpeg);base64,(.+)", u or "", re.S)
    if not m:
        return None
    open(out, "wb").write(base64.b64decode(m[2])); return out


def c3_op(p, op, it):
    d = c3_load(p)
    if op == "add":
        it["id"] = int(time.time() * 1000); it["n"] = max([i["n"] for i in d["items"]] + [0]) + 1
        it["state"] = "open"; it["at"] = datetime.datetime.now().strftime("%d/%m %H:%M")
        shot = it.pop("shot", None)
        if shot:
            it["shot"] = png_from_dataurl(shot, f"{C3SHOTS}/{os.path.basename(c3file(p))[:16]}-{it['id']}.png")
        d["items"].append(it)
    elif op == "update":
        for i in d["items"]:
            if i["id"] == it.get("id"):
                i.update({k: v for k, v in it.items() if k == "text"}); i["state"] = "open"
    elif op == "delete":
        d["items"] = [i for i in d["items"] if i["id"] != it.get("id")]
    c3_save(p, d); return d


def c3_send(p, note="", snapshot=""):
    import shutil
    d = c3_load(p); items = [i for i in d["items"] if i.get("state") != "sent"]
    if not items:
        return None
    stamp = datetime.datetime.now().strftime("%y%m%d-%H%M"); base = os.path.splitext(os.path.basename(p))[0]
    out_dir = f"{MARK}/{stamp} {base}"[:200]; os.makedirs(out_dir, exist_ok=True)
    view = png_from_dataurl(snapshot, f"{out_dir}/view.png")
    f3 = lambda v: ", ".join(f"{x:.3f}" for x in v) if isinstance(v, list) else ""
    lines = [f"# 3D markup — {base}", f"Model: {p}", f"Sent: {stamp}" + (f" · note: {note}" if note else ""),
             f"View snapshot: {view}" if view else "", "Points: viewer = metres, Y-up. model = file units (3dm: mm, Z-up).",
             "Show a comment again: POST /api/view {path, focus:[name], camera:{pos,target}} (viewer values below).", ""]
    for i in items:
        user = i.get("user") or {}
        shot = None
        if i.get("shot") and os.path.exists(i["shot"]):
            shot = f"{out_dir}/{i['n']:02d}.png"; shutil.copy(i["shot"], shot)
        cam = i.get("camera") or {}
        lines += [f"## {i['n']}. {i.get('name') or '(no name)'}", (i.get("text") or "").strip() or "(no comment)",
                  f"- layer / class: {i.get('layer') or i.get('cls') or ''}", f"- type: {i.get('type') or ''}",
                  f"- id: {i.get('guid') or ''}" + (f" · tag {i['tag']}" if i.get("tag") else ""),
                  *( [f"- user text: " + "; ".join(f"{k}={v}" for k, v in user.items())] if user else [] ),
                  f"- point (viewer): {f3(i.get('point'))}" + (f" · point (model): {f3(i.get('mpoint'))}" if i.get("mpoint") else ""),
                  f"- camera (viewer): pos {f3(cam.get('pos'))} · target {f3(cam.get('target'))}",
                  f"- snapshot: {shot}" if shot else "", ""]
        i["state"] = "sent"; i["sentAt"] = stamp
    open(f"{out_dir}/comments.md", "w").write("\n".join(x for x in lines if x is not None)); c3_save(p, d)
    wake(f"[3d markup] {HUMAN} commented on {base}: {len(items)} element comment(s). Report: {out_dir}/comments.md — check, then tell the author what to fix.")
    return {"ok": True, "count": len(items), "report": f"{out_dir}/comments.md"}


# ---------- artifact tracking: arrival time, seen / NEW per item, the human's comments, REV chains ----------
# arrivals.json {key: {at, approx, status, statusAt}}  key = path (or title)  · first run backfills from date + file mtime
# seen.json     {key: epoch}  set when the human opens the item (or "mark all seen"); shared by Mac app and phone
ART_LOCK = threading.Lock()
ART_OLD = re.compile(r"(?i)supersed|withdrawn")
REV_RE = re.compile(r"(?i)\bREV\s*(\d+)")


def art_key(a):
    return a.get("path") or a.get("title", "")


def art_doc(a):
    """Document identity without REV: (key, rev) or (None, 0). Name from the file when it has a REV, else from the title."""
    p = a.get("path") or ""; b = os.path.basename(p); ext = os.path.splitext(p)[1].lower() if os.path.splitext(p)[1][1:].isalnum() else ""
    n = os.path.splitext(b)[0] if REV_RE.search(b) else (a.get("title") or "")
    m = REV_RE.search(n)
    if not m:
        return None, 0
    k = re.sub(r"\([^)]*\)", " ", REV_RE.sub(" ", n))
    k = re.sub(r"^\d{6}[\s_]+", "", k.strip()); k = re.sub(r"[^a-z0-9]+", " ", k.lower()).strip()
    return f"{k}|{ext}", int(m[1])


def _ts(s, fmt):
    try:
        return time.mktime(time.strptime(s, fmt))
    except Exception:
        return None


def art_cm_index():
    """The human's markup per file: 2D boxes (markups/<sha>.json) + 3D pins (<sha>-3d.json), indexed by path and by file name
    (Folder Manager moves old REVs to _superseded, so the path at comment time can differ). n = sent, open = drafts."""
    by_path = {}
    for f in glob.glob(f"{MARK}/*.json"):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        p = d.get("path") or ""; c = by_path.setdefault(p, {"n": 0, "open": 0, "at": 0})
        for i in d.get("items", []):
            if i.get("state") == "sent":
                c["n"] += 1; c["at"] = max(c["at"], _ts(i.get("sentAt", ""), "%y%m%d-%H%M") or 0)
            else:
                c["open"] += 1
    by_name = {}
    for p, c in by_path.items():
        b = by_name.setdefault(os.path.basename(p), {"n": 0, "open": 0, "at": 0})
        b["n"] += c["n"]; b["open"] += c["open"]; b["at"] = max(b["at"], c["at"])
    return by_path, by_name


def art_enrich(arts):
    """Copy of the artifact list with: key, arrivedAt, arrivedApprox, statusAt2, new, seenAt, cm, rev, prev, next, afterCm, newerAfterCm."""
    now = time.time()
    with ART_LOCK:
        arr = jload("arrivals.json", None); first = arr is None; arr = arr or {}
        seen = jload("seen.json", None); seed = seen is None; seen = seen or {}
        dirty = False
        for a in arts:
            k = art_key(a); r = arr.get(k)
            if r is None:
                mt = None
                try:
                    mt = os.stat(a["path"]).st_mtime if a.get("path") else None
                except Exception:
                    pass
                if first:          # backfill: file time when it matches the listed day, else the day only
                    d0 = _ts(a.get("date", ""), "%Y-%m-%d")
                    if mt and time.strftime("%Y-%m-%d", time.localtime(mt)) == a.get("date"):
                        at, approx = mt, False
                    else:
                        at, approx = (d0 + 12 * 3600 if d0 else now), True
                else:              # new item: file time if it was written in the last 6 h, else now
                    at, approx = (mt if mt and 0 <= now - mt < 6 * 3600 else now), False
                r = arr[k] = {"at": at, "approx": approx, "status": a.get("status", "")}; dirty = True
            elif r.get("status") != a.get("status", ""):
                r["status"] = a.get("status", ""); r["statusAt"] = now; dirty = True
        if dirty:
            jsave("arrivals.json", arr)
        docs = {}
        for a in arts:
            d, rv = art_doc(a)
            if d:
                docs.setdefault(d, []).append((rv, a))
        ch = {}
        for d, xs in docs.items():
            xs.sort(key=lambda x: -x[0])
            for i, (rv, a) in enumerate(xs):
                ch[id(a)] = (rv, xs[i - 1][1] if i else None, xs[i + 1][1] if i + 1 < len(xs) else None)
        bp, bn = art_cm_index(); z = {"n": 0, "open": 0, "at": 0}
        cms = {id(a): (bn.get(os.path.basename(a["path"])) or bp.get(a["path"]) or z) if a.get("path") else z for a in arts}
        today0 = time.mktime(datetime.date.today().timetuple())
        out = []
        for a in arts:
            k = art_key(a); r = arr[art_key(a)]; rv, newer, older = ch.get(id(a), (0, None, None)); cm = cms[id(a)]
            old = bool(ART_OLD.search(a.get("status", ""))) or newer is not None
            x = dict(a); x.update({"key": k, "arrivedAt": int(r["at"]), "arrivedApprox": bool(r.get("approx")), "cm": cm,
                                    "statusAt2": int(r.get("statusAt", 0)), "old": old, "rev": rv})
            ref = lambda b: {"rev": ch[id(b)][0], "title": b.get("title", ""), "path": b.get("path", "")}
            if older is not None: x["prev"] = ref(older)
            if newer is not None:
                x["next"] = ref(newer)
                if cm["n"] and arr[art_key(newer)]["at"] > cm["at"]:
                    x["newerAfterCm"] = ch[id(newer)][0]
            if not cm["n"] and not old:      # latest REV, no comments yet: did the human comment an older REV before this one came?
                o = older
                while o is not None:
                    oc = cms[id(o)]
                    if oc["n"]:
                        if r["at"] > oc["at"]:
                            x["afterCm"] = {"rev": ch[id(o)][0], "n": oc["n"], "at": int(oc["at"])}
                        break
                    o = ch[id(o)][2]
            if seed and (old or cm["n"] or r["at"] < today0):     # first run: only today's live, uncommented items stay NEW
                seen[k] = now
            x["seenAt"] = int(seen.get(k, 0))
            x["new"] = (not old) and r["at"] > max(seen.get(k, 0), cm["at"])
            out.append(x)
        if seed:
            jsave("seen.json", seen)
    return out


def art_seen(data):
    """POST /api/seen  {keys:[...]} | {all:true} | {restore:{key:epoch|0}} → {ok, prev}"""
    art_enrich(jload("artifacts.json", []))          # makes sure seen.json exists (first-run seed)
    with ART_LOCK:
        s = jload("seen.json", {}); prev = {}
        if isinstance(data.get("restore"), dict):
            for k, v in data["restore"].items():
                if v: s[str(k)] = v
                else: s.pop(str(k), None)
        keys = [art_key(a) for a in jload("artifacts.json", [])] if data.get("all") else [str(k) for k in (data.get("keys") or [])][:500]
        for k in keys:
            prev[k] = s.get(k, 0); s[k] = time.time()
        jsave("seen.json", s)
    return {"ok": True, "prev": prev}


def view_open(path, title=None, focus=None, camera=None, old=None):
    """Open a file in the artifacts tab. 3D: focus = element names/tags/guids to highlight + frame, camera = {pos,target} (viewer metres, Y-up).
    old = a second PDF -> compare view (old vs path)."""
    p = allowed(path)
    if not p:
        return None
    kind = KINDS.get(os.path.splitext(p)[1].lower(), "other")
    item = {"id": int(time.time() * 1000), "title": title or os.path.basename(p), "path": p, "kind": kind,
            "state": "converting" if kind in ("ifc", "step", "3dm") else "ready", "at": datetime.datetime.now().strftime("%H:%M")}
    if old:
        o = allowed(old)
        if not o or kind != "pdf" or not o.lower().endswith(".pdf"):
            return None
        item.update({"kind": "compare", "old": o, "title": title or f"Compare · {os.path.splitext(os.path.basename(p))[0]}"})
    if focus:
        item["focus"] = [str(x)[:120] for x in (focus if isinstance(focus, list) else [focus])][:50]
    if isinstance(camera, dict):
        item["camera"] = {k: [float(x) for x in camera[k]][:3] for k in ("pos", "target") if isinstance(camera.get(k), list)}
    def add(v):
        v["items"] = [i for i in v["items"] if not (i["path"] == p and i.get("old") == item.get("old"))][-19:] + [item]; v["current"] = item["id"]
    vset(add)
    if kind in ("ifc", "step", "3dm"):
        threading.Thread(target=convert, args=(item["id"], p), daemon=True).start()
    return item


def coord_now():
    """What the coordinator is doing right now, for its live avatar: state + short label + who it talks to."""
    me = next((a for a in sessions() if a["name"] == COORD), None)
    t = CHAT.transcript()
    if not t:
        return {"state": "away"}
    fd = FEEDS.get("__coord")
    if not fd or fd.path != t:
        fd = FEEDS["__coord"] = Feed(t)
    ev = (fd.get()["messages"] or [{}])[-1]
    busy = bool(me) and me["status"] in ("busy", "shell")
    out = {"state": "idle" if not busy else "working", "label": "", "with": None, "tool": None}
    if not me:
        out["state"] = "away"; out["label"] = "not running"
    elif busy and ev.get("who") == "tool":
        tool, txt = ev["tool"], ev.get("text", ""); out["tool"] = tool
        if tool == "SendMessage":
            m = re.match(r"→ ([^:]+):\s*(.*)", txt); out["state"] = "talking"
            out["with"] = m[1].strip() if m else None; out["label"] = (m[2] if m else txt)[:90]
        elif tool in ("Agent", "Task"):
            out["state"] = "briefing"; out["label"] = txt[:90]
        elif tool in ("Read", "Grep", "Glob", "WebFetch", "WebSearch"):
            out["state"] = "reading"; out["label"] = os.path.basename(txt)[:90] if tool == "Read" else txt[:90]
        elif tool in ("Write", "Edit"):
            out["state"] = "writing"; out["label"] = os.path.basename(txt)[:90]
        else:
            out["label"] = txt[:90]
    elif busy:
        out["state"] = "thinking"
    elif ev.get("who") == "coord" or ev.get("who") == "agent":
        out["label"] = "waiting for you"
    return out


# ---------- team / watchdog ----------
def team():
    out, now = [], time.time()
    for f in sorted(os.listdir(STATUS)) if os.path.isdir(STATUS) else []:
        p = f"{STATUS}/{f}"
        try:
            name, doing, needs, t = (open(p).read().split("\n") + ["", "", "", ""])[:4]
        except Exception:
            continue
        age = int((now - os.path.getmtime(p)) / 60)
        st = "idle" if doing.strip().lower() in ("idle", "") else ("offline" if "OFFLINE" in doing.upper() else "working")
        watch = "ok"
        if st == "working":
            watch = "alert" if age >= 15 else ("warn" if age >= 5 else "ok")   # silence watchdog (Paperclip idea 3)
        out.append({"name": name, "label": name, "doing": doing, "needs": needs, "time": t,
                    "age": age, "state": st, "watch": watch, "color": COLORS.get(name, "#8a8478")})
    live = {a["name"]: a for a in sessions()}                # live state from Claude Code itself beats the hand-written status
    have = {a["name"] for a in out}
    for name in ORDER:                                        # new team member with a live session but no status file yet
        if name in live and name not in have:
            out.append({"name": name, "label": name, "doing": "", "needs": "", "time": "", "age": 0, "state": "idle",
                        "watch": "ok", "color": COLORS.get(name, "#8a8478")})
    for a in out:
        lv = live.get(a["name"])
        if not lv:
            a["state"], a["watch"], a["live"] = "offline", "ok", "not running"
        elif lv["status"] == "starting":
            a["state"], a["watch"], a["live"] = "idle", "alert", "waiting for your Yes (trust question)"
        else:
            busy = lv["status"] in ("busy", "shell")
            a["state"], a["live"] = ("working" if busy else "idle"), ("working now" if busy else "idle")
            a["watch"] = "ok"
            if busy and a["doing"].strip().lower() in ("idle", ""):
                a["doing"] = "working…"
            if not busy and a["doing"].strip() and not a["doing"].strip().lower().startswith("idle"):
                a["doing"] = "last: " + a["doing"]
        a["where"] = "background" if lv and lv.get("tmux") else ("terminal window" if lv else "")
    out.sort(key=lambda a: ORDER.index(a["name"]) if a["name"] in ORDER else 99)
    return out


def activity(n=12):
    rows = []
    try:
        for line in open(LOG, encoding="utf-8").read().splitlines()[::-1]:
            m = re.match(r"\|\s*(\d{4}-\d\d-\d\d \d\d:\d\d)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|", line)
            if m:
                rows.append({"when": m[1], "who": m[2].strip(), "what": m[3].strip(), "item": m[4].strip()})
            elif line.startswith("- 20"):
                rows.append({"when": line[2:18], "who": "", "what": "", "item": line[19:].strip()[:140]})
            if len(rows) >= n:
                break
    except Exception:
        pass
    return rows


def daylog():
    d = datetime.date.today().isoformat(); p = f"{OFFICE}/log/{d}.md"
    return {"date": d, "text": open(p).read() if os.path.exists(p) else ""}


def where():
    try:
        if not LOCATION:
            return ""
        return subprocess.run(["bash", LOCATION], capture_output=True, text=True, timeout=3).stdout.strip().split(" (")[0]
    except Exception:
        return "?"


def board():
    tm = team(); tasks = jload("tasks.json", []); cards = [c for c in jload("cards.json", []) if c.get("state") == "open"]
    summ = jload("summary.json", {})
    donow = summ.get("now") or ([f"Answer: {c['q']}" for c in cards[:3]] +
                                 [t["title"] for t in tasks if t.get("state") == "waiting"])[:3]   # idea 7 fallback
    return {"now": datetime.datetime.now().strftime("%a %d %b · %H:%M"), "where": where(), "team": tm, "tasks": tasks,
            "cards": cards, "donow": donow, "status": summ.get("status", ""), "artifacts": (ae := art_enrich(jload("artifacts.json", [])))[:14], "artNew": sum(1 for a in ae if a["new"]),
            "routines": jload("routines.json", []), "drafts": jload("drafts.json", []), "activity": activity(), "log": daylog(),
            "watch": [a["label"] for a in tm if a["watch"] != "ok"]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("content-type", ctype); self.send_header("cache-control", "no-store")
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/requests"):                # requests from agents to the human (what would help them)
            return self.send(200, json.dumps(jload("requests.json", [])))
        if self.path.startswith("/api/lanes"):                   # flow lanes: /api/lanes (list) · /api/lanes/<id> (one lane + events)
            from urllib.parse import unquote
            lid = unquote(self.path.split("?")[0][len("/api/lanes"):].strip("/"))
            if lid:
                L = flow.api_lane(lid)
                return self.send(200 if L else 404, json.dumps(L or {"error": "no such lane"}))
            return self.send(200, json.dumps(flow.api_lanes()))
        if self.path.startswith("/api/timeline"):                # project timeline (Procurer rebuilds the JSON in place)
            tp = TIMELINE
            try:
                d = json.load(open(tp, encoding="utf-8")); d["_mtime"] = os.path.getmtime(tp); d["_path"] = tp
                return self.send(200, json.dumps(d))
            except FileNotFoundError:
                return self.send(404, json.dumps({"error": "timeline.json not found"}))
            except Exception as e:
                return self.send(500, json.dumps({"error": "could not read timeline.json: " + str(e)[:200]}))
        if self.path.startswith("/api/board"):
            return self.send(200, json.dumps(board()))
        if self.path.startswith("/api/chat"):
            m = re.search(r"before=(\d+)", self.path)
            return self.send(200, json.dumps(CHAT.get(int(m[1]) if m else None)))
        if self.path.startswith("/api/drafts"):
            return self.send(200, json.dumps(jload("drafts.json", [])))
        if self.path.startswith("/api/coord"):
            return self.send(200, json.dumps(coord_now()))
        if self.path.startswith("/coord-avatar.js"):
            return self.send(200, render(f"{HERE}/coord-avatar.js"), "text/javascript")
        if self.path.startswith("/avatars.js"):
            return self.send(200, open(f"{HERE}/avatars.js", "rb").read(), "text/javascript")
        if self.path.startswith("/api/comms"):
            m = re.search(r"since=([\d.]+)", self.path)
            return self.send(200, json.dumps(comms(float(m[1]) if m else 0.0)))
        if self.path.startswith("/api/agentcard?"):
            from urllib.parse import parse_qs, urlparse
            return self.send(200, json.dumps(agent_card(parse_qs(urlparse(self.path).query).get("name", [""])[0])))
        if self.path.startswith("/api/subagents"):
            return self.send(200, json.dumps(subagents()))
        if self.path.startswith("/api/profile?"):                # agent profile page (profile_api.py)
            from urllib.parse import parse_qs, urlparse
            return self.send(200, json.dumps(profile_api.profile(parse_qs(urlparse(self.path).query).get("name", [""])[0], sys.modules[__name__])))
        if self.path.split("?")[0] in ("/profile.js", "/profile.css"):
            f = self.path.split("?")[0][1:]
            return self.send(200, render(f"{HERE}/{f}"), "text/javascript" if f.endswith(".js") else "text/css")
        if self.path.startswith("/api/agents"):
            return self.send(200, json.dumps([{k: v for k, v in a.items() if k != "transcript"} for a in sessions()]))
        if self.path.startswith("/api/agent?"):
            from urllib.parse import parse_qs, urlparse
            return self.send(200, json.dumps(agent_feed(parse_qs(urlparse(self.path).query).get("name", [""])[0])))
        if self.path.startswith("/api/artifacts"):            # full list for the Artifacts library (board sends 14)
            return self.send(200, json.dumps(art_enrich(jload("artifacts.json", []))))
        if self.path.startswith("/api/view"):
            return self.send(200, json.dumps(vload()))
        if self.path.startswith("/api/pdfinfo?") or self.path.startswith("/api/pdfpage?"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query); p = allowed(q.get("p", [""])[0])
            if not p or not p.lower().endswith(".pdf"):
                return self.send(404, "{}")
            if self.path.startswith("/api/pdfinfo"):
                return self.send(200, json.dumps(pdf_info(p)))
            f = pdf_page(p, int(q.get("n", ["1"])[0]), int(q.get("dpi", ["100"])[0]))
            return self.send(200, open(f, "rb").read(), "image/png") if os.path.exists(f) else self.send(404, "{}")
        if self.path.startswith("/api/markup?"):
            from urllib.parse import parse_qs, urlparse
            p = allowed(parse_qs(urlparse(self.path).query).get("p", [""])[0])
            return self.send(200, json.dumps(mload(p))) if p else self.send(404, "{}")
        if self.path.startswith("/api/pdfrevs?"):
            from urllib.parse import parse_qs, urlparse
            p = allowed(parse_qs(urlparse(self.path).query).get("p", [""])[0])
            return self.send(200, json.dumps(pdf_revs(p) if p and p.lower().endswith(".pdf") else []))
        if self.path.startswith("/api/comments3d?"):
            from urllib.parse import parse_qs, urlparse
            p = allowed(parse_qs(urlparse(self.path).query).get("p", [""])[0])
            return self.send(200, json.dumps(c3_load(p))) if p else self.send(404, "{}")
        if self.path.startswith("/api/c3shot?"):              # stored snapshot of one 3D comment
            from urllib.parse import parse_qs, urlparse
            f = os.path.realpath(parse_qs(urlparse(self.path).query).get("f", [""])[0])
            return self.send(200, open(f, "rb").read(), "image/png") if f.startswith(C3SHOTS + "/") and os.path.isfile(f) else self.send(404, "{}")
        if self.path.startswith("/api/file?"):
            from urllib.parse import parse_qs, urlparse
            import mimetypes
            p = allowed(parse_qs(urlparse(self.path).query).get("p", [""])[0])
            if not p:
                return self.send(404, "{}")
            ct = "model/gltf-binary" if p.endswith(".glb") else (mimetypes.guess_type(p)[0] or "application/octet-stream")
            if ct.startswith("text/") or p.endswith((".md", ".csv")):
                ct = "text/plain; charset=utf-8" if not p.endswith(".html") else "text/html; charset=utf-8"
            size = os.path.getsize(p); rng = self.headers.get("Range", "")
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m and (m[1] or m[2]):                         # video needs byte ranges (WebKit plays mp4 only with 206)
                a = int(m[1]) if m[1] else max(0, size - int(m[2])); b = int(m[2]) if (m[1] and m[2]) else size - 1
                b = min(b, size - 1)
                with open(p, "rb") as fh:
                    fh.seek(a); data = fh.read(b - a + 1)
                self.send_response(206); self.send_header("content-type", ct); self.send_header("accept-ranges", "bytes")
                self.send_header("content-range", f"bytes {a}-{b}/{size}"); self.send_header("content-length", str(len(data)))
                self.end_headers(); self.wfile.write(data); return
            self.send_response(200); self.send_header("content-type", ct); self.send_header("accept-ranges", "bytes")
            self.send_header("content-length", str(size)); self.send_header("cache-control", "no-store"); self.end_headers()
            with open(p, "rb") as fh:
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk: break
                    self.wfile.write(chunk)
            return
        if self.path.startswith("/vendor/") and re.fullmatch(r"/vendor/[\w.-]+\.js", self.path):
            f = f"{HERE}{self.path}"
            return self.send(200, open(f, "rb").read(), "text/javascript") if os.path.exists(f) else self.send(404, "{}")
        if self.path.startswith("/pdfview.html"):
            return self.send(200, render(f"{HERE}/pdfview.html"), "text/html; charset=utf-8")
        if self.path.startswith("/compare.html"):
            return self.send(200, render(f"{HERE}/compare.html"), "text/html; charset=utf-8")
        if self.path.startswith("/viewer.html"):
            return self.send(200, render(f"{HERE}/viewer.html"), "text/html; charset=utf-8")
        m = re.fullmatch(r"/(preview-[\w-]+\.html)", self.path.split("?")[0])   # design previews
        if m and os.path.exists(f"{HERE}/{m.group(1)}"):
            return self.send(200, open(f"{HERE}/{m.group(1)}", "rb").read(), "text/html; charset=utf-8")
        if self.path == "/favicon.svg":
            return self.send(200, open(f"{HERE}/favicon.svg", "rb").read(), "image/svg+xml")
        if self.path in ("/manifest.webmanifest", "/manifest.json"):   # phone: "Add to Home Screen" opens full-screen
            return self.send(200, json.dumps({"name": "Officina", "short_name": "Officina", "start_url": "/", "scope": "/", "display": "standalone",
                "background_color": "#ffffff", "theme_color": "#ffffff", "icons": [
                    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}), "application/manifest+json")
        icon = {"/apple-touch-icon.png": "icon-180.png", "/apple-touch-icon-precomposed.png": "icon-180.png",
                "/icon-180.png": "icon-180.png", "/icon-192.png": "icon-192.png", "/icon-512.png": "icon-512.png"}.get(self.path.split("?")[0])
        if icon and os.path.exists(f"{HERE}/{icon}"):
            return self.send(200, open(f"{HERE}/{icon}", "rb").read(), "image/png")
        if self.path.split("?")[0] in ("/", "/index.html"):   # also /?pane=artifacts (pop-out window)
            return self.send(200, render(f"{HERE}/index.html"), "text/html; charset=utf-8")
        self.send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("content-length", 0) or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/say":                          # chat input → coordinator
            t = (data.get("text") or "").strip()
            if not t:
                return self.send(400, '{"ok":false}')
            if data.get("to"):                              # agent tab composer: the coordinator relays it with SendMessage
                t = f"[for {data['to']} — please relay] {t}"
            threading.Thread(target=wake, args=(t,), daemon=True).start()
            return self.send(200, '{"ok":true}')
        if self.path == "/api/requests/reply":              # the human answers an agent request → saved + the coordinator relays it at once
            reply = str(data.get("reply") or "").strip()[:2000]
            if not reply:
                return self.send(400, '{"ok":false}')
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

            def f(r):
                r["reply"] = reply; r["replyAt"] = now
                if r.get("state") != "done":
                    r["state"] = "answered"
            it = rq_update(data.get("id"), f)
            if not it:
                return self.send(404, '{"ok":false}')
            threading.Thread(target=wake, args=(f"[request reply] {it.get('from')} #{it.get('id')}: {reply} (to: {it.get('text')})",), daemon=True).start()
            return self.send(200, json.dumps({"ok": True, "item": it}))
        if self.path == "/api/requests/state":              # open | answered | done
            st = data.get("state")
            if st not in ("open", "answered", "done"):
                return self.send(400, '{"ok":false}')
            it = rq_update(data.get("id"), lambda r: r.__setitem__("state", st))
            return self.send(200 if it else 404, json.dumps({"ok": bool(it), "item": it}))
        if self.path == "/api/card":                         # idea 6: answer a question / approval card
            cards = jload("cards.json", [])
            for c in cards:
                if c["id"] == data.get("id") and c.get("state") == "open":
                    c["state"] = "answered"; c["answer"] = data.get("answer", ""); c["answeredAt"] = datetime.datetime.now().strftime("%d/%m %H:%M")
                    threading.Thread(target=wake, args=(f"[card #{c['id']}] {c['q']} → {c['answer']}",), daemon=True).start()
            jsave("cards.json", cards)
            return self.send(200, '{"ok":true}')
        if self.path == "/api/task":                         # ideas 1 + 5
            tasks = jload("tasks.json", [])
            if data.get("id") is not None and data.get("state") in STATES:
                for t in tasks:
                    if t["id"] == data["id"]:
                        t["state"] = data["state"]; t["updated"] = datetime.datetime.now().strftime("%d/%m %H:%M")
                        if t.get("owner") != HUMAN:
                            threading.Thread(target=wake, args=(f"[task #{t['id']}] {HUMAN} set '{t['title']}' → {t['state']}",), daemon=True).start()
            elif data.get("title"):
                t = {"id": max([t["id"] for t in tasks] + [0]) + 1, "title": data["title"][:200], "owner": data.get("owner", COORD),
                     "state": "waiting" if data.get("owner") == HUMAN else "doing", "topic": data.get("topic", ""),
                     "updated": datetime.datetime.now().strftime("%d/%m %H:%M")}
                tasks.append(t)
                if t["owner"] != HUMAN:
                    threading.Thread(target=wake, args=(f"[new task #{t['id']} for {t['owner']}] {t['title']}",), daemon=True).start()
            jsave("tasks.json", tasks)
            return self.send(200, '{"ok":true}')
        if self.path == "/api/view":                         # open a file in the app's artifacts tab (+ focus/camera for 3D, old for PDF compare)
            it = view_open(data.get("path"), data.get("title"), data.get("focus"), data.get("camera"), data.get("old"))
            return self.send(200 if it else 400, json.dumps(it or {"ok": False}))
        if self.path == "/api/markup":                       # add / update / delete one markup box
            p = allowed(data.get("path"))
            if not p:
                return self.send(400, '{"ok":false}')
            d = mload(p); op = data.get("op"); it = data.get("item") or {}
            if op == "add":
                it["id"] = int(time.time() * 1000); it["n"] = max([i["n"] for i in d["items"]] + [0]) + 1
                it["state"] = "open"; it["at"] = datetime.datetime.now().strftime("%d/%m %H:%M"); d["items"].append(it)
            elif op == "update":
                for i in d["items"]:
                    if i["id"] == it.get("id"):
                        i.update({k: v for k, v in it.items() if k in ("text", "x", "y", "w", "h")}); i["state"] = "open"
            elif op == "delete":
                d["items"] = [i for i in d["items"] if i["id"] != it.get("id")]
            msave(p, d); return self.send(200, json.dumps(d))
        if self.path == "/api/comments3d":                   # 3D element comments: add / update / delete
            p = allowed(data.get("path"))
            if not p:
                return self.send(400, '{"ok":false}')
            return self.send(200, json.dumps(c3_op(p, data.get("op"), data.get("item") or {})))
        if self.path == "/api/comments3d/send":
            p = allowed(data.get("path"))
            r = c3_send(p, data.get("note", ""), data.get("snapshot", "")) if p else None
            return self.send(200 if r else 400, json.dumps(r or {"ok": False}))
        if self.path == "/api/markup/send":
            p = allowed(data.get("path"))
            r = msend(p, data.get("note", "")) if p else None
            return self.send(200 if r else 400, json.dumps(r or {"ok": False}))
        if self.path == "/api/drafts":                       # plain-text drafts for the human to copy (messages, commands)
            d = jload("drafts.json", [])
            if data.get("op") == "add" and data.get("text"):
                d = [x for x in d if x.get("title") != data.get("title")]
                d.insert(0, {"id": int(time.time() * 1000), "title": data.get("title") or "draft", "text": data["text"],
                             "at": datetime.datetime.now().strftime("%d/%m %H:%M")})
            elif data.get("op") == "delete":
                d = [x for x in d if x["id"] != data.get("id")]
            jsave("drafts.json", d[:30]); return self.send(200, json.dumps(d))
        if self.path == "/api/copy":                         # put text on the Mac clipboard (pbcopy), reliable inside the app
            subprocess.run(["/usr/bin/pbcopy"], input=(data.get("text") or "").encode("utf-8"), timeout=5)
            return self.send(200, '{"ok":true}')
        if self.path == "/api/artifact":                     # the human sets a file status from the Artifacts page ("Mark sent")
            st = (data.get("status") or "").strip()[:80]
            arts = jload("artifacts.json", []); hit = None
            for x in arts:
                if x.get("title") == data.get("title") and (x.get("path") or "") == (data.get("path") or ""):
                    hit = x; break
            if not hit or not st:
                return self.send(400, '{"ok":false}')
            old = hit.get("status", ""); hit["status"] = st; hit["statusAt"] = datetime.datetime.now().strftime("%d/%m %H:%M")
            jsave("artifacts.json", arts)
            if old != st:
                threading.Thread(target=wake, args=(f"[file] {HUMAN} set '{hit['title']}' → {st} (was: {old})",), daemon=True).start()
            return self.send(200, json.dumps({"ok": True, "artifacts": art_enrich(arts)}))
        if self.path == "/api/seen":                         # the human saw these files (opened / mark all seen) → NEW badge off
            return self.send(200, json.dumps(art_seen(data)))
        if self.path == "/api/viewset":                      # auto-open on/off, switch or close an item
            def upd(v):
                if "auto" in data: v["auto"] = bool(data["auto"])
                if "current" in data: v["current"] = data["current"]
                if data.get("closeAll"):
                    v["items"], v["current"] = [], None
                if "close" in data:
                    v["items"] = [i for i in v["items"] if i["id"] != data["close"]]
                    if v["current"] == data["close"]: v["current"] = v["items"][-1]["id"] if v["items"] else None
            return self.send(200, json.dumps(vset(upd)))
        if self.path == "/api/profile/perm":                 # per-agent overrides file only, after the human's confirm in the UI
            code, out = profile_api.perm_change(data, sys.modules[__name__]); return self.send(code, json.dumps(out))
        if self.path == "/api/profile/vote":                 # the human's daily 1-10 rating -> votes/<today>/<human>.json
            code, out = profile_api.vote(data, sys.modules[__name__]); return self.send(code, json.dumps(out))
        if self.path == "/api/open":
            p = os.path.realpath(data.get("path") or "")
            if not p.startswith(ROOTS) or not os.path.exists(p):
                return self.send(400, '{"ok":false}')
            subprocess.Popen(["open", p] if data.get("app") else ["open", "-R", p]); return self.send(200, '{"ok":true}')
        self.send(404, "{}")


if __name__ == "__main__":
    try:
        flow.start(OFFICE)
    except Exception as e:
        print("flow lanes did not start:", e)
    print(f"Officina on http://localhost:{PORT}")
    # optional: also listen on a private Tailscale IP (config tailnet_ip), e.g. for your phone. Never 0.0.0.0.

    def tailnet():
        while TAILNET_IP:
            try:
                ThreadingHTTPServer((TAILNET_IP, PORT), H).serve_forever()
            except OSError:
                time.sleep(30)                                   # Tailscale not up yet: retry
    threading.Thread(target=tailnet, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
