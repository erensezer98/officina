#!/usr/bin/env python3
"""Flow lanes + stuck alarm: where is each deliverable (author -> reviewer -> filer -> human -> sent), and who is stuck.

Read-only. Sources: agent transcripts (SendMessage first lines), <office>/flow.jsonl (office.sh flow tags),
artifacts.json, cards.json, ~/.claude/sessions/*.json, flow/hooks/<session_id>.json (Claude Code Notification/Stop hooks,
first source for "waiting" / "idle"), tmux capture-pane (read-only, never send-keys; fallback only when no hook file).
Server: flow.start(office_dir) starts a 30 s thread; flow.api_lanes() / flow.api_lane(id) feed /api/lanes.
CLI:    python3 flow.py --replay 2026-01-01T00:00Z [--until 2026-01-02T00:00Z]   rebuild lanes from your transcripts, print them, no pushes
        python3 flow.py --test                                                   run the synthetic checks (no pushes)
Pushes only when flow/config.json has "push": true AND config.json has a push_script (default: dry run, logged to flow/alerts.log).
Lane roles: the reviewer and the filer are the team members named in config.json "reviewer" / "filer" (default Judge / Folder Manager).
"""
import json, os, re, sys, time, glob, threading, subprocess, datetime
from zoneinfo import ZoneInfo

import settings as S
HOME = S.HOME
OFFICE = S.OFFICE
FLOWD = f"{OFFICE}/flow"
PROJ = S.PROJECTS
SESS = S.SESSIONS
PUSH = S.PUSH                                    # optional script "Title" "Text" [url]; empty = never push
TMUX = S.which("tmux")
LOCAL_TZ = ZoneInfo(S.CFG["timezone"]) if S.CFG.get("timezone") else datetime.datetime.now().astimezone().tzinfo
UTC = datetime.timezone.utc
LINK_BASE = f"http://{S.TAILNET_IP or '127.0.0.1'}:{S.PORT}/#lanes/"
COORD, HUMAN = S.COORD, S.HUMAN
REVIEWER = S.CFG.get("reviewer", "Judge")
FILER = S.CFG.get("filer", "Folder Manager")
AGENTS = S.ORDER + [HUMAN]
AUTHORS = set(S.ORDER) - {REVIEWER, FILER}

# ---------- time ----------
def now_utc():
    return datetime.datetime.now(UTC)

def parse_utc(s):
    """transcript timestamp '2026-10-21T23:39:51.209Z' -> aware UTC"""
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return None

def parse_local(s):
    """flow.jsonl / cards '2026-10-22 02:29:20' (local time, no zone) -> aware UTC"""
    try:
        return datetime.datetime.fromisoformat(str(s)).replace(tzinfo=LOCAL_TZ).astimezone(UTC)
    except Exception:
        return None

def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None

def local_hm(t):
    return t.astimezone(LOCAL_TZ).strftime("%H:%M") if t else ""

def quiet(t=None):
    lt = (t or now_utc()).astimezone(LOCAL_TZ)
    m = lt.hour * 60 + lt.minute
    return m >= 23 * 60 or m < 7 * 60 + 30

def jload(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d

def jsave(p, v):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    json.dump(v, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)

# ---------- names + keys ----------
def norm_agent(s):
    s = re.sub(r"\s*\[.*?\]\s*$", "", str(s or "")).strip()
    if s.lower().startswith(COORD.lower()):
        return COORD
    for a in AGENTS:
        if s.lower() == a.lower():
            return a
    return s

STOP = set("the a an please quick check review re-check recheck set pdf pdfs ifc file files of for and to in on at is are with new now".split())
REV_RE = re.compile(r"\bREV ?(\d{2})\b", re.I)
DATE_RE = re.compile(r"\b(26\d{4})\b")

def tokens(name):
    s = REV_RE.sub(" ", str(name).lower())
    s = DATE_RE.sub(" ", s)
    return [w for w in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", s) if w not in STOP][:8]

def slug(name):
    return "-".join(tokens(name)) or "lane"

def jacc(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0

def rev_of(text):
    m = REV_RE.search(text or "")
    if m:
        return m[1]
    m = DATE_RE.search(text or "")
    return m[1] if m else ""

WEAK = set("both two three all it this that these those confirmed restarted done ready ok yes no go status update fixed sent filed set sets pdfs one first second last same each every".split())
NAMES_RX = "|".join(re.escape(n) for n in sorted(S.ORDER, key=len, reverse=True))
LEAD = re.compile(r"^\s*(?:" + NAMES_RX + r")\s*(?:\(cc\)|cc)?\s*[:,\-–]?\s*", re.I)
TRIG = re.compile(r"(urgent|priority|please|quick|re-?check|check|review|file|replace|judge|pass(?:ed)?|not yet|cc|fyi|the|ok|done|now|again|here is|here's)\b[\s:,!.\-–]*", re.I)

def deliverable(line):
    """'Modeller: please file (Judge PASS 1/10) the stair B bracket REV02 next to REV01' -> 'stair B bracket'"""
    s = re.split(r"~/|/Users/|https?://", line)[0]
    s = re.sub(r"\([^)]*\)?", " ", s)
    s = re.sub(r"^\s*(\d{1,2}|[A-Ha-h])\)\s*", "", s)
    for _ in range(3):
        s = LEAD.sub("", s)
    m = REV_RE.search(s) or DATE_RE.search(s)
    if m:
        name = s[:m.start()]
        if DATE_RE.match(m.group(0)) and len(tokens(name)) < 2:      # "260101 roof panels ..." date first
            name = s[m.end():]
    else:
        name = re.split(r"[:.;!?]\s|,\s|\s[-–]\s", s + " ")[0]
    name = re.split(r"[:;]\s", name)[-1]
    for _ in range(4):
        name = re.sub(r"^\s*" + TRIG.pattern, "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" ,.:-–")
    tk = tokens(name)
    if not tk or all(w in WEAK for w in tk) or len(name) > 90:
        return ""
    return name

def items(line):
    """one first line -> [(name, rev)]: 'A REV02 + B REV21' = two items; no name -> the work folder in the path"""
    head = re.split(r"~/|/Users/|https?://", line)[0]
    head = re.sub(r"\([^)]*\)?", " ", head).replace('"', " ").replace("“", " ").replace("”", " ")
    first, rest = (re.split(r"(?<=\w)[.;]\s", head, maxsplit=1) + [""])[:2]
    segs = [x for x in re.split(r"\s\+\s", first) if x.strip()] or [head]
    segs = segs[:1] + [x for x in segs[1:] if rev_of(x)]          # extra items only when they carry their own REV
    out = [(deliverable(x), rev_of(x) or (rev_of(head) if len(segs) == 1 else "")) for x in segs]
    out = [o for o in out if o[0]]
    if not out:
        m = re.search(r"work/([^/]+)/(?:out|work)\b", line)
        if m and deliverable(m[1]):
            out = [(deliverable(m[1]), rev_of(line) or rev_of(m[1]))]
    return out or [("", rev_of(head))]

# ---------- event detection (spec §3) ----------
R_SUBMIT = re.compile(r"(please review|quick (re-?)?check please|re-?check please|priority review|urgent quick check|quick check please|please (re-?)?check)", re.I)
R_REOPEN = re.compile(r"(same files?|same folder|overwrit)", re.I)
R_CHANGE = re.compile(r"\b(BLOCK|NOT (YET )?PASS|FAIL|[Nn]ot passed( yet)?)\b")
R_PASS = re.compile(r"\bPASS\b")
R_COND = re.compile(r"(once|after) \d* ?(small )?(fix|change)", re.I)
R_HOLD = re.compile(r"\bHOLD\b")
R_FILEREQ = re.compile(r"please (file|replace)", re.I)
R_FILED = re.compile(r"\b(is|are) filed\b|filed in\b|updated in place", re.I)
R_LINK = re.compile(r"https?://[^\s)\]]+")                       # the filed copy's link (cloud drive, share, ...)
_H = re.escape(HUMAN)
R_TOHUMAN = re.compile(rf"(needs {_H}'?s OK|waits? for {_H}'?s OK|waiting for {_H}|HOLD {_H})", re.I)
R_CLEAR = re.compile(r"^\W*(GO|go ahead|hold (is )?(released|lifted)|release the hold)\b", re.I)

def detect(frm, to, line, full):
    """-> list of (event, extra) for one SendMessage first line"""
    out = []
    if frm == REVIEWER and to != REVIEWER:
        if R_CHANGE.search(line):
            out.append(("change-list", {}))
        elif R_PASS.search(line):
            out.append(("pass", {"conditional": bool(R_COND.search(line))}))
        if R_HOLD.search(line) and not re.search(rf"HOLD {_H}", line, re.I):
            out.append(("hold", {}))
    elif to == REVIEWER and frm != REVIEWER:
        if R_SUBMIT.search(line):
            out.append(("reopen" if R_REOPEN.search(line) else "submit", {}))
    if to == FILER and frm != FILER and R_FILEREQ.search(line):
        out.append(("file-request", {}))
    if frm == FILER and R_FILED.search(line):
        lk = R_LINK.findall(full)
        out.append(("filed", {"link": lk[0] if lk else "", "links": lk[:4]}))
    if to == COORD and frm != COORD:
        if R_TOHUMAN.search(line):
            out.append(("to-human", {"hold": bool(re.search(r"\bHOLD\b", line))}))
        elif R_CLEAR.search(LEAD.sub("", line)):
            out.append(("clear", {}))
    return out

# ---------- transcript tailer ----------
def seek_ts(path, t):
    """byte offset of the first line with timestamp >= t (binary search; lines are in time order)"""
    size = os.path.getsize(path)
    target = iso(t)

    def ts_at(off):
        with open(path, "rb") as f:
            f.seek(off)
            if off:
                f.readline()
            for _ in range(400):
                pos = f.tell(); raw = f.readline()
                if not raw:
                    return size, None
                m = re.search(rb'"timestamp":"([0-9T:\-\.]+)Z?"', raw[-600:]) or re.search(rb'"timestamp":"([0-9T:\-\.]+)Z?"', raw[:4000])
                if m and not raw.startswith(b'{"type":"api-request-blob"'):
                    return pos, m[1].decode()[:19] + "Z"
            return size, None
    lo, hi = 0, size
    while hi - lo > 1 << 16:
        mid = (lo + hi) // 2
        pos, ts = ts_at(mid)
        if ts is None or ts >= target:
            hi = mid
        else:
            lo = mid
    return lo

class Tail:
    def __init__(self, path, off):
        self.path, self.off = path, off
        self.agent = None
        self.votes = {}
        self.usage = 0; self.usage_ts = None
        self.ask = {}          # pending AskUserQuestion id -> ts
        self.mtime = 0

    def read(self, sink, limit=None):
        try:
            size = os.path.getsize(self.path); self.mtime = os.path.getmtime(self.path)
        except OSError:
            return
        if size < self.off:
            self.off = 0
        if size == self.off:
            return
        with open(self.path, "rb") as f:
            f.seek(self.off)
            last_usage = None
            while True:
                raw = f.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    break                      # half-written line: read it next time
                self.off += len(raw)
                if raw.startswith(b'{"type":"api-request-blob"'):
                    continue
                if b'"usage"' in raw and b'"role":"assistant"' in raw:
                    last_usage = raw
                hit_ask = self.ask and any(k.encode() in raw for k in self.ask)
                if b'"SendMessage"' not in raw and b'AskUserQuestion' not in raw and not hit_ask:
                    continue
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                if d.get("isSidechain"):
                    continue
                ts = parse_utc(d.get("timestamp"))
                m = d.get("message") or {}
                if d.get("type") == "user" and isinstance(m.get("content"), list):
                    for c in m["content"]:
                        if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in self.ask:
                            self.ask.pop(c["tool_use_id"], None)
                    continue
                if d.get("type") != "assistant":
                    continue
                for c in m.get("content") or []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    if c.get("name") == "AskUserQuestion":
                        self.ask[c["id"]] = ts
                    if c.get("name") != "SendMessage":
                        continue
                    i = c.get("input") or {}
                    to = str(i.get("to") or i.get("recipient") or "")
                    if re.fullmatch(r"a[0-9a-f]{12,}", to) or to == "*":
                        continue
                    msg = str(i.get("message") or "")
                    first = (msg.strip().splitlines() or [""])[0][:400]
                    lead = re.match(r"^\s*(" + NAMES_RX + r")\b", first, re.I)
                    if lead:
                        k = norm_agent(lead[1]); self.votes[k] = self.votes.get(k, 0) + 1
                    sink.append({"id": c.get("id"), "ts": ts, "to": norm_agent(to), "line": first, "full": msg[:4000], "tail": self})
            if last_usage:
                try:
                    d = json.loads(last_usage); u = (d.get("message") or {}).get("usage") or {}
                    self.usage = int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
                    self.usage_ts = parse_utc(d.get("timestamp"))
                except Exception:
                    pass

    def who(self, live):
        if self.agent:
            return self.agent
        sid = os.path.basename(self.path)[:-6]
        if sid in live:
            return live[sid]
        if self.votes:
            return max(self.votes, key=self.votes.get)
        return None

def live_sessions():
    """sessionId -> {name, status, statusAt, tmux, pid} for sessions whose pid runs"""
    out = {}
    for f in glob.glob(f"{SESS}/*.json"):
        d = jload(f, None)
        if not d:
            continue
        try:
            os.kill(int(d["pid"]), 0)
        except Exception:
            continue
        out[d.get("sessionId")] = {"name": norm_agent(d.get("name") or ""), "status": d.get("status"), "statusAt": (d.get("statusUpdatedAt") or 0) / 1000,
                                   "tmux": d.get("tmux"), "pid": d.get("pid"), "sid": d.get("sessionId"), "startedAt": (d.get("startedAt") or 0) / 1000}
    return out

# ---------- hook signals (Claude Code Notification / Stop hooks, see README) ----------
PERM_RE = re.compile(r"permission|approv|needs your (ok|attention|approval)", re.I)
HOOK_TOL = 3   # s: hook ts has 1 s resolution (local time); transcript lines have ms

def hook_signals(d=None):
    """flow/hooks/<session_id>.json -> {sid: {event, ts, message, cwd, transcript, t (aware UTC)}}"""
    out = {}
    for f in glob.glob(f"{d or FLOWD + '/hooks'}/*.json"):
        h = jload(f, None)
        if not isinstance(h, dict) or h.get("event") not in ("Notification", "Stop"):
            continue
        t = parse_local(h.get("ts"))
        if t:
            out[os.path.basename(f)[:-5]] = {**h, "t": t}
    return out

def last_line_ts(path):
    """UTC time of the last transcript line that has a timestamp (reads the last 256 kB); None if unreadable."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 262144)); buf = f.read()
    except OSError:
        return None
    for raw in reversed(buf.split(b"\n")):
        if b'"timestamp"' not in raw or raw.startswith(b'{"type":"api-request-blob"'):
            continue
        try:
            t = parse_utc(json.loads(raw).get("timestamp"))
        except Exception:
            continue
        if t:
            return t
    return None

def hook_state(sid, hooks, transcript=None, started=0):
    """-> None (no usable hook file: caller falls back to tmux) or
          {"kind": "permission"|"input"|"idle"|"active", "since": aware UTC, "msg": str}
       Notification newer than the last transcript line = waiting (permission prompt or input);
       Stop newer than the last transcript line = turn ended (idle); hook older than the transcript = active again."""
    h = hooks.get(sid)
    if not h or (started and h["t"].timestamp() < started - HOOK_TOL):
        return None
    last = last_line_ts(h.get("transcript") or transcript or f"{PROJ}/{sid}.jsonl")
    if last and h["t"] < last - datetime.timedelta(seconds=HOOK_TOL):
        return {"kind": "active", "since": last, "msg": ""}
    msg = str(h.get("message") or "")
    if h["event"] == "Stop":
        return {"kind": "idle", "since": h["t"], "msg": ""}
    return {"kind": "permission" if PERM_RE.search(msg) else "input", "since": h["t"], "msg": msg}

# ---------- lane builder ----------
ORDER = {"submit": 0, "reopen": 0, "change-list": 1, "pass": 2, "hold": 3, "file-request": 4, "filed": 5, "to-human": 6, "clear": 7, "sent": 8}
TAGMAP = {"change": "change-list", "file": "file-request"}

def author_of(ev):
    frm, to = ev.get("by") or "", ev.get("to") or ""
    if ev["event"] in ("submit", "reopen", "file-request") and frm in AUTHORS:
        return frm
    if frm == REVIEWER and to in AUTHORS - {COORD}:
        return to
    if frm == FILER and to in AUTHORS - {COORD}:
        return to
    if frm in AUTHORS - {COORD}:
        return frm
    return None

def build(events, artifacts, now):
    events = sorted(events, key=lambda e: (e["ts"], ORDER.get(e["event"], 9), 0 if e["src"] == "tag" else 1))
    lanes = []

    def find(ev, toks, rev, au):
        best, bt = None, None
        for L in lanes:
            if L["closed_at"] and (ev["ts"] - L["closed_at"]).total_seconds() > 6 * 3600:
                continue
            if au and L["author"] and au != L["author"]:
                continue
            j = max(jacc(toks, n) for n in L["names"])
            gap = (ev["ts"] - L["last"]).total_seconds()
            nxt = rev.isdigit() and L["rev"].isdigit() and len(rev) == len(L["rev"]) == 2 and int(rev) == int(L["rev"]) + 1
            samedate = len(rev) == 6 and rev == L["rev"] and set(toks) & set(L["tokens"]) and gap < 3 * 3600
            cont = samedate or nxt and au and au == L["author"] and set(toks) & set(L["tokens"]) and gap < 3 * 3600   # "production machining REV21" after "steel production REV20"
            if not cont and (j < 0.6 or (j < 1 and gap > 8 * 3600)):
                continue
            if rev and L["rev"] and rev.isdigit() and L["rev"].isdigit() and len(rev) == len(L["rev"]) == 2 and int(rev) < int(L["rev"]) and ev["event"] in ("submit", "reopen"):
                continue                                        # REV went back = another series (T2)
            if bt is None or L["last"] > bt:
                best, bt = L, L["last"]
        return best

    for ev in events:
        au = author_of(ev)
        toks = tokens(ev["name"]) if ev.get("name") and ev["event"] != "clear" else []
        L = find(ev, toks, ev["rev"], au) if toks else None
        if not L and not toks:                                  # no name ("URGENT: please HOLD the mail", "GO"): sender's / author's latest lane
            cand = [x for x in lanes if (au and x["author"] == au) or ev.get("by") in (x["author"], None)]
            cand = [x for x in cand if (ev["ts"] - x["last"]).total_seconds() < 3 * 3600]
            if ev["event"] == "clear":                          # "GO" releases the lane that this sender put on hold
                held = [x for x in lanes if x["events"] and any(e["event"] == "to-human" and e.get("by") == ev.get("by") for e in x["events"])
                        and x["events"][-1]["event"] != "clear" and (ev["ts"] - x["last"]).total_seconds() < 3 * 3600]
                cand = held or cand
            L = max(cand, key=lambda x: x["last"]) if cand else None
            if not L:
                continue
        if not L and ev["event"] in ("to-human", "clear", "hold"):
            continue                                            # these only attach to an existing lane
        if not L:
            L = {"id": slug(ev["name"]), "title": ev["name"], "tokens": toks, "names": [toks], "author": au, "rev": "", "events": [], "last": ev["ts"], "closed_at": None}
            base, n = L["id"], 2
            while any(x["id"] == L["id"] for x in lanes):
                L["id"] = f"{base}-{n}"; n += 1
            lanes.append(L)
        if ev.get("name") and len(ev["name"]) > len(L["title"]) and ev["src"] == "parse":
            L["title"] = ev["name"]
        if toks and toks not in L["names"]:
            L["names"].append(toks)
        if not L["author"] and au:
            L["author"] = au
        if ev["rev"] and not (len(ev["rev"]) == 6 and len(L["rev"]) == 2) and (not L["rev"] or len(L["rev"]) == 6 or (ev["rev"].isdigit() and L["rev"].isdigit() and int(ev["rev"]) >= int(L["rev"]))):
            L["rev"] = ev["rev"]
        L["events"].append(ev); L["last"] = max(L["last"], ev["ts"])
        if ev["event"] == "sent":
            L["closed_at"] = ev["ts"]

    out = []
    for L in lanes:
        # tags win over the parser for the same (rev, event); parser cc copies de-dup within 3 min
        tagged = {(e["rev"], e["event"]) for e in L["events"] if e["src"] == "tag"}
        evs, seen = [], []
        for e in L["events"]:
            if e["src"] == "parse" and (e["rev"], e["event"]) in tagged:
                continue
            if any(s["event"] == e["event"] and s["rev"] == e["rev"] and abs((s["ts"] - e["ts"]).total_seconds()) <= 180 for s in seen):
                continue
            seen.append(e); evs.append(e)
        out.append(lane_state(L, evs, artifacts, now))
    return out

def lane_state(L, evs, artifacts, now):
    au = L["author"] or "Modeller"
    stages, revs, rounds, flags, link = [], {}, {}, [], ""
    wait = None                                               # {"since","note"} waiting on the human by event
    cur = None
    filed = False

    def open_(stage, agent, t, **kw):
        nonlocal cur
        if cur and cur["to"] is None:
            cur["to"] = iso(t)
        cur = {"stage": stage, "agent": agent, "from": iso(t), "to": None, **kw}
        stages.append(cur)

    def close(t, **kw):
        if cur and cur["to"] is None:
            cur["to"] = iso(t); cur.update(kw)

    for e in evs:
        t, ev, rev = e["ts"], e["event"], e["rev"] or L["rev"]
        if len(rev) == 6 and len(L["rev"]) == 2:
            rev = L["rev"]
        if rev:
            for r in list(revs):
                if r != rev and r.isdigit() and rev.isdigit() and len(r) == len(rev) and int(r) < int(rev):
                    revs[r] = "superseded"
            revs.setdefault(rev, "open")
        if ev in ("submit", "reopen"):
            wait = None
            if ev == "reopen" or filed:
                if "reopened" not in flags:
                    flags.append("reopened")
            open_("judge", REVIEWER, t, rev=rev)
        elif ev == "change-list":
            rounds[rev] = rounds.get(rev, 0) + 1
            if not (cur and cur["stage"] == "judge" and cur["to"] is None):
                open_("judge", REVIEWER, t, rev=rev)
            close(t, verdict="change-list")
            open_(stage_of(au), au, t, rev=rev, note="fixing")
        elif ev == "pass":
            if revs.get(rev) not in ("pass", "filed", "sent"):
                rounds[rev] = rounds.get(rev, 0) + 1
            if not (cur and cur["stage"] == "judge" and cur["to"] is None):
                open_("judge", REVIEWER, t, rev=rev)
            close(t, verdict="PASS" + (" (conditional)" if e.get("conditional") else ""))
            revs[rev] = "pass"
            open_(stage_of(au), au, t, rev=rev, note="PASS, to file")
        elif ev == "hold":
            if "hold" not in flags:
                flags.append("hold")
        elif ev == "file-request":
            open_("fm", FILER, t, rev=rev)
        elif ev == "filed":
            if not (cur and cur["stage"] == "fm" and cur["to"] is None):
                open_("fm", FILER, t, rev=rev)
            link = e.get("link") or link
            close(t, link=link)
            filed = True; revs[rev] = "filed"
            open_("filed", "", t, rev=rev)
        elif ev == "to-human":
            wait = {"since": iso(t), "note": e["line"][:140], "hold": e.get("hold")}
            if e.get("hold") and "hold" not in flags:
                flags.append("hold")
        elif ev == "clear":
            wait = None
            if "hold" in flags:
                flags.remove("hold")
        elif ev == "sent":
            wait = None
            open_("sent", "", t, rev=rev); close(t); revs[rev] = "sent"

    # artifacts override the final state (match by title tokens + REV)
    art = None
    for a in artifacts or []:
        ttl = a.get("title") or ""
        if max(jacc(tokens(ttl), n) for n in L["names"]) < 0.5:
            continue
        r = rev_of(ttl)
        st = (a.get("status") or "").lower()
        if r and r in revs and st.startswith("supersed"):
            revs[r] = "superseded"
        if r == L["rev"] or (not r and not L["rev"]):
            art = a
    status = ""
    if art:
        st = (art.get("status") or "").lower()
        status = art.get("status") or ""
        mid = cur and cur["stage"] == "judge" and cur["to"] is None
        last_ev = evs[-1]["event"] if evs else ""
        if re.match(r"^sent|.*\bsent to\b", st) and not wait and last_ev in ("filed", "sent", "pass", "file-request", "clear", ""):
            if not (cur and cur["stage"] == "sent"):
                open_("sent", "", L["last"]); close(L["last"])
            revs[L["rev"]] = "sent"
        elif re.match(r"^(for approval|ready|hold)", st) and not mid and (filed or (cur and cur["stage"] in ("filed", "fm"))):
            if cur and cur["stage"] == "filed":
                cur["stage"], cur["agent"] = "human", HUMAN
            elif not (cur and cur["stage"] == "human"):
                open_("human", HUMAN, L["last"])
            revs[L["rev"]] = "hold" if st.startswith("hold") else "ready" if st.startswith("ready") else "for approval"
        elif st.startswith("supersed"):
            revs[L["rev"]] = "superseded"
    if wait and not (cur and cur["stage"] in ("human", "sent")):
        pass
    stage = cur["stage"] if cur else "author"
    closed = stage == "sent" or (L["rev"] and revs.get(L["rev"]) == "superseded")
    waiting = bool(wait) or stage == "human"
    since = parse_utc(wait["since"]) if wait else (parse_utc(cur["from"]) if cur else L["last"])
    if stage == "human" and cur and not wait:
        since = parse_utc(cur["from"])
    owner = HUMAN if waiting else (cur["agent"] if cur and cur["to"] is None and cur["agent"] else "")
    minor = len(evs) < 2 and not any(e["src"] == "tag" for e in evs)
    return {"id": L["id"], "title": L["title"], "minor": minor, "key": " ".join(L["tokens"]), "author": L["author"], "rev": L["rev"], "stage": stage,
            "status": status, "owner": owner, "waiting": waiting, "wait": wait, "closed": bool(closed), "stages": stages,
            "revs": revs, "rounds": rounds, "flags": flags, "link": link, "path": (art or {}).get("path", ""),
            "since": iso(since), "updated": iso(L["last"]),
            "events": [{"ts": iso(e["ts"]), "event": e["event"], "rev": e["rev"], "by": e.get("by") or "", "to": e.get("to") or "",
                        "line": e["line"][:240], "link": e.get("link", ""), "src": e["src"]} for e in evs]}

def stage_of(agent):
    """lane stage key of the author = its slug ("Modeller" -> "modeller"); the page shows the agent's name."""
    return re.sub(r"[^a-z0-9]+", "-", (agent or "author").lower()).strip("-") or "author"

# ---------- engine ----------
class Engine:
    def __init__(self, office=OFFICE, push=None, replay_from=None, until=None):
        self.office = office
        self.lock = threading.Lock()
        self.tails = {}
        self.parsed = []           # parser events (dicts with ts aware)
        self.lanes = []
        self.agents = []
        self.alerts_active = []
        self.prompt_seen = {}      # sid -> (first seen utc, pane hash)
        self.replay_from = replay_from
        self.until = until
        self.push_override = push
        self.updated = None
        self.state = jload(f"{FLOWD}/state.json", {"offsets": {}}) if not replay_from else {"offsets": {}}
        if not replay_from and self.state.get("offsets"):          # parser events survive a restart (offsets point past them)
            for e in jload(f"{FLOWD}/events.json", []):
                t = parse_utc(e.get("ts"))
                if t:
                    self.parsed.append({**e, "ts": t})
            if not self.parsed:
                self.state = {"offsets": {}}

    # -- sources --
    def tags(self):
        out = []
        try:
            lines = open(f"{self.office}/flow.jsonl", encoding="utf-8").read().splitlines()
        except Exception:
            lines = []
        for ln in lines:
            try:
                d = json.loads(ln)
            except Exception:
                continue
            t = parse_local(d.get("ts"))
            if not t:
                continue
            ev = TAGMAP.get(d.get("event"), d.get("event"))
            if ev not in ORDER:
                continue
            rv = rev_of(d.get("rev") or "") or rev_of(d.get("key") or "")
            if (d.get("rev") or "") == "" and DATE_RE.search(d.get("key") or ""):
                rv = rev_of(d.get("key"))
            note = d.get("note") or ""
            lk = R_LINK.findall(note)
            out.append({"ts": t, "event": ev, "name": re.sub(r"^\s*26\d{4}\s+", "", d.get("key") or ""), "rev": rv, "by": norm_agent(d.get("by") or ""),
                        "to": "", "line": f"{d.get('event')} {d.get('key')} {d.get('rev') or ''} {note}".strip(), "link": lk[0] if lk else "", "src": "tag"})
        return out

    def files(self, since):
        out = []
        for p in glob.glob(f"{PROJ}/*.jsonl"):
            try:
                if os.path.getmtime(p) >= since.timestamp():
                    out.append(p)
            except OSError:
                pass
        return out

    def tick(self, now=None):
        now = now or now_utc()
        start = self.replay_from or (now - datetime.timedelta(hours=36))
        live = live_sessions()
        sid_name = {k: v["name"] for k, v in live.items()}
        for p in self.files(start):
            if p not in self.tails:
                off = self.state["offsets"].get(p) if not self.replay_from else None
                if off is None or off > os.path.getsize(p):
                    off = seek_ts(p, start)
                self.tails[p] = Tail(p, off)
            sink = []
            self.tails[p].read(sink)
            for m in sink:
                if self.until and m["ts"] and m["ts"] > self.until:
                    continue
                frm = m["tail"].who(sid_name)
                if not frm or not m["ts"]:
                    continue
                its = None
                for ev, extra in detect(frm, m["to"], m["line"], m["full"]):
                    its = its or items(m["line"])
                    for name, rv in its:
                        self.parsed.append({"ts": m["ts"], "event": ev, "name": name, "rev": rv, "by": frm, "to": m["to"],
                                            "line": m["line"], "src": "parse", "link": extra.get("link", ""), **{k: v for k, v in extra.items() if k != "link"}})
        # forget parser events older than 4 days
        cut = now - datetime.timedelta(days=4)
        self.parsed = [e for e in self.parsed if e["ts"] >= cut]
        tags = [t for t in self.tags() if t["ts"] >= start - datetime.timedelta(hours=12) and (not self.until or t["ts"] <= self.until)]
        arts = jload(f"{self.office}/artifacts.json", [])
        lanes = build(self.parsed + tags, arts, now)
        agents = [] if self.replay_from else self.agent_strip(live, now)
        with self.lock:
            self.lanes, self.agents, self.updated = lanes, agents, now
        if not self.replay_from:
            self.state["offsets"] = {p: t.off for p, t in self.tails.items()}
            try:
                jsave(f"{FLOWD}/events.json", [{**e, "ts": iso(e["ts"])} for e in self.parsed])
                jsave(f"{FLOWD}/state.json", self.state)
            except Exception:
                pass

    def agent_strip(self, live, now):
        out = []
        by_path = {os.path.basename(p)[:-6]: t for p, t in self.tails.items()}
        hooks = hook_signals()
        for sid, s in live.items():
            t = by_path.get(sid)
            if t is None:
                p = f"{PROJ}/{sid}.jsonl"
                if os.path.exists(p):
                    t = self.tails[p] = Tail(p, max(0, os.path.getsize(p) - 2_000_000)); t.read([])
            if t is not None and not getattr(t, "u0", False):   # context % right after a restart: last usage in the last 3 MB
                t.u0 = True
                if not t.usage:
                    try:
                        with open(t.path, "rb") as f:
                            f.seek(max(0, os.path.getsize(t.path) - 3_000_000)); buf = f.read()
                        for raw in reversed(buf.split(b"\n")):
                            if b'"usage"' in raw and b'"role":"assistant"' in raw and not raw.startswith(b'{"type":"api-request-blob"'):
                                u = (json.loads(raw).get("message") or {}).get("usage") or {}
                                t.usage = int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
                                break
                    except Exception:
                        pass
            pend, status, src = None, s["status"], None
            hs = hook_state(sid, hooks, t.path if t else None, s.get("startedAt") or 0)
            if hs is not None:                                  # hooks first (exact signal)
                self.prompt_seen.pop(sid, None)
                src = "hook"
                if hs["kind"] == "permission":
                    pend = hs["since"]
                elif hs["kind"] in ("idle", "input") and status == "busy":
                    status = "idle"                             # turn ended after the last transcript line
            elif s["status"] == "busy" and s.get("tmux") and not self.replay_from:
                pend = self.prompt(sid, s["tmux"], now)         # fallback: read-only pane capture
                src = "tmux"
            else:
                self.prompt_seen.pop(sid, None)
            ask = min(t.ask.values()) if t and t.ask else None
            out.append({"name": s["name"], "sid": sid, "status": status, "statusAt": s["statusAt"], "tokens": t.usage if t else 0,
                        "ctx": round((t.usage if t else 0) / 1_000_000 * 100), "mtime": t.mtime if t else 0,
                        "prompt": iso(pend) if pend else None, "ask": iso(ask) if ask else None,
                        "wait": hs["kind"] if hs and hs["kind"] in ("permission", "input") else None,
                        "waitMsg": hs["msg"] if hs else "", "hookAt": iso(hs["since"]) if hs else None, "src": src})
        best = {}
        for a in out:                                       # one row per agent (the coordinator can have a parked + a live session)
            b = best.get(a["name"])
            if not b or (a["status"] == "busy", a["mtime"]) > (b["status"] == "busy", b["mtime"]):
                best[a["name"]] = a
        out = list(best.values())
        order = {a: i for i, a in enumerate(AGENTS)}
        out.sort(key=lambda a: order.get(a["name"], 99))
        return out

    PROMPT_RE = re.compile(r"Do you want to (proceed|make this edit|create)|❯ 1\. Yes")

    def prompt(self, sid, pane, now, text=None):
        """read-only: tmux capture-pane -p (never send-keys). Returns first-seen time while a prompt is on screen."""
        if text is None:
            target = pane.split(":", 1)[1].split(".", 1)[-1] if ":" in pane and "%" in pane else pane
            try:
                text = subprocess.run([TMUX, "capture-pane", "-p", "-t", target, "-S", "-15"], capture_output=True, text=True, timeout=3).stdout
            except Exception:
                return None
        if self.PROMPT_RE.search(text or ""):
            h = hash(text)
            first = self.prompt_seen.get(sid)
            if not first:
                self.prompt_seen[sid] = (now, h)
                return now
            return first[0]
        self.prompt_seen.pop(sid, None)
        return None

    # -- stuck rules (spec §4) --
    def due(self, now):
        """-> list of {key, rule, title, text, lane, age_min, blocked}"""
        out = []
        cards = jload(f"{self.office}/cards.json", [])
        for c in cards:
            if c.get("state") == "answered":
                continue
            t = None
            try:
                t = datetime.datetime.strptime(f"{now.astimezone(LOCAL_TZ).year}/{c.get('at')}", "%Y/%d/%m %H:%M").replace(tzinfo=LOCAL_TZ).astimezone(UTC)
            except Exception:
                pass
            if not t:
                continue
            age = (now - t).total_seconds() / 60
            if age > 10:
                out.append({"key": f"card|{c.get('id')}||", "rule": "card", "blocked": True, "age": age, "lane": "",
                            "title": f"⏳ {HUMAN}: {c.get('from') or COORD} asks ({int(age)} min)", "text": str(c.get("q") or "")[:180]})
        with self.lock:
            lanes, agents = list(self.lanes), list(self.agents)
        idle = {a["name"]: a for a in agents}
        for L in lanes:
            if L["closed"]:
                continue
            fresh = (now - parse_utc(L["updated"])).total_seconds() < 12 * 3600
            since = parse_utc(L["since"]) or now
            age = (now - since).total_seconds() / 60
            hold = bool(L["wait"] and L["wait"].get("hold"))
            if L["waiting"] and (age > 10 or hold) and fresh:
                what = "HOLD" if L["wait"] and L["wait"].get("hold") else "waits for approval" if L["stage"] == "human" else "waits for you"
                out.append({"key": f"human|{L['id']}|{L['rev']}|", "rule": "human", "blocked": True, "age": age, "lane": L["id"], "once": True,
                            "title": f"⏳ {HUMAN}: {short(L['title'])}{' REV' + L['rev'] if L['rev'] and len(L['rev']) == 2 else ''} {what} ({int(age)} min)",
                            "text": (L["wait"] or {}).get("note") or f"{L['title']} · {L['status'] or L['stage']}"})
            elif not L["waiting"] and L["owner"] and fresh and age > 20 and not L.get("minor") and L["stage"] not in ("filed", "sent"):
                a = idle.get(L["owner"])
                quiet_owner = a and (a["status"] == "idle" or now.timestamp() - (a["mtime"] or 0) > 1200)
                if quiet_owner:
                    out.append({"key": f"noprog|{L['id']}|{L['rev']}|", "rule": "noprog", "blocked": False, "age": age, "lane": L["id"],
                                "title": f"⏳ {L['owner']}: {short(L['title'])} no progress ({int(age)} min)", "text": f"Stage {L['stage']} open since {local_hm(since)}; {L['owner']} is idle."})
            for r, n in (L["rounds"] or {}).items():
                cl = sum(1 for e in L["events"] if e["event"] == "change-list" and e["rev"] == r)
                if cl >= 3:
                    out.append({"key": f"loop|{L['id']}|{r}|", "rule": "loop", "blocked": False, "age": 0, "lane": L["id"], "once": True,
                                "title": f"⏳ Judge: {short(L['title'])} REV{r} in a loop ({cl} change-lists)", "text": "Three or more Judge change-lists on one REV."})
        for a in agents:
            if a["prompt"]:
                age = (now - parse_utc(a["prompt"])).total_seconds() / 60
                if age > 3:
                    out.append({"key": f"prompt|||{a['sid']}", "rule": "prompt", "blocked": True, "age": age, "lane": "",
                                "title": f"⏳ {a['name']}: permission prompt waits ({int(age)} min)",
                                "text": (a.get("waitMsg") or f"{a['name']} is blocked on a yes/no prompt") + " (in its terminal)."})
            if a["ask"]:
                age = (now - parse_utc(a["ask"])).total_seconds() / 60
                if age > 5:
                    out.append({"key": f"dialog|||{a['sid']}", "rule": "dialog", "blocked": True, "age": age, "lane": "",
                                "title": f"⏳ {a['name']}: question dialog waits ({int(age)} min)", "text": f"{a['name']} asks you a question in its terminal."})
            if a["tokens"] > 800_000:
                out.append({"key": f"ctx|||{a['sid']}", "rule": "ctx", "blocked": False, "age": 0, "lane": "", "once": True,
                            "title": f"⏳ {a['name']}: context {a['ctx']} %", "text": f"{a['name']} is at {a['tokens']:,} tokens. Time to clear or hand over."})
        return out

    def alert(self, now=None, send=True):
        """de-dup, double-age repeats (max 3), quiet hours queue, bundle > 2. Returns pushes made [(title,text,url)]."""
        now = now or now_utc()
        cfg = jload(f"{FLOWD}/config.json", {"push": False})
        live_push = cfg.get("push") is True if self.push_override is None else self.push_override
        st = jload(f"{FLOWD}/alerts.json", {"sent": {}, "queue": [], "baseline": False})
        due = self.due(now)
        keys = {d["key"] for d in due}
        for k in list(st["sent"]):
            if k not in keys:
                st["sent"].pop(k)                               # condition ended: clear
        st["queue"] = [q for q in st["queue"] if q["key"] in keys]
        if live_push and send and not st.get("push_was"):        # push just switched on: start from a clean baseline (no burst)
            st["baseline"] = False
        st["push_was"] = bool(live_push and send)
        if not st.get("baseline"):                              # first run: what is already due counts as sent (no burst on deploy)
            for d in due:
                st["sent"][d["key"]] = {"n": 1, "age": d["age"], "at": iso(now), "baseline": True}
            st["baseline"] = True
            jsave(f"{FLOWD}/alerts.json", st)
            self.alerts_active = due
            return []
        out = []
        qh = quiet(now)
        for d in due:
            s = st["sent"].get(d["key"])
            if s:
                if d.get("once") or s["n"] >= 3 or d["age"] < 2 * s["age"] or s.get("baseline"):
                    continue
            if qh and not d["blocked"]:
                if not any(q["key"] == d["key"] for q in st["queue"]):
                    st["queue"].append({"key": d["key"], "title": d["title"]})
                continue
            st["sent"][d["key"]] = {"n": (s["n"] + 1) if s else 1, "age": max(d["age"], 1), "at": iso(now)}
            out.append((d["title"], d["text"], LINK_BASE + d["lane"] if d["lane"] else LINK_BASE.rstrip("/")))
        lt = now.astimezone(LOCAL_TZ)
        if not qh and st["queue"] and lt.hour * 60 + lt.minute >= 7 * 60 + 30:
            n = len(st["queue"])
            out.append((f"⏳ Morning: {n} thing{'s' if n > 1 else ''} stuck overnight", "; ".join(q["title"].replace("⏳ ", "") for q in st["queue"])[:300], LINK_BASE.rstrip("/")))
            for q in st["queue"]:
                st["sent"][q["key"]] = {"n": 1, "age": 1, "at": iso(now)}
            st["queue"] = []
        if len(out) > 2:
            out = [(f"⏳ {len(out)} things wait for you", "; ".join(t.replace("⏳ ", "") for t, _, _ in out)[:300], LINK_BASE.rstrip("/"))]
        jsave(f"{FLOWD}/alerts.json", st)
        self.alerts_active = due
        for t, x, u in out:
            line = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {'PUSH' if (send and live_push) else 'DRY'} {t} | {x[:160]}\n"
            try:
                open(f"{FLOWD}/alerts.log", "a", encoding="utf-8").write(line)
            except Exception:
                pass
            if send and live_push:
                try:
                    if PUSH:
                        subprocess.run([PUSH, t, x, u], capture_output=True, timeout=20)   # output not logged (never print the topic)
                except Exception:
                    pass
        return out

def short(t):
    t = str(t)
    return t if len(t) <= 34 else t[:32].rstrip() + "…"

# ---------- server glue ----------
ENG = None

def start(office=OFFICE):
    global ENG
    if ENG:
        return ENG
    os.makedirs(FLOWD, exist_ok=True)
    if not os.path.exists(f"{FLOWD}/config.json"):
        jsave(f"{FLOWD}/config.json", {"push": False, "_note": "set push true to send phone alerts via config.json push_script; false = dry run (flow/alerts.log)"})
    ENG = Engine(office)

    def loop():
        while True:
            try:
                ENG.tick()
                ENG.alert()
            except Exception as e:
                try:
                    open(f"{FLOWD}/error.log", "a").write(f"{datetime.datetime.now()} {e!r}\n")
                except Exception:
                    pass
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()
    return ENG

def api_lanes():
    if not ENG:
        return {"lanes": [], "agents": [], "alerts": [], "updated": None, "loading": True}
    with ENG.lock:
        lanes = [{k: v for k, v in L.items() if k != "events"} | {"n": len(L["events"])} for L in ENG.lanes]
        agents = list(ENG.agents)
    al = [{k: d[k] for k in ("rule", "title", "text", "lane", "blocked")} | {"age": round(d["age"])} for d in (ENG.alerts_active or [])]
    cards = [c for c in jload(f"{OFFICE}/cards.json", []) if c.get("state") != "answered"]
    cfg = jload(f"{FLOWD}/config.json", {})
    return {"lanes": lanes, "agents": agents, "alerts": al, "cards": len(cards), "updated": iso(ENG.updated), "push": cfg.get("push") is True,
            "loading": ENG.updated is None}

def api_lane(lid):
    if not ENG:
        return None
    with ENG.lock:
        return next((L for L in ENG.lanes if L["id"] == lid), None)

# ---------- CLI: replay + tests ----------
def show(lanes):
    for L in sorted(lanes, key=lambda x: x["updated"]):
        print(f"- {L['id']:<44} REV {L['rev'] or '-':<7} stage={L['stage']:<9} waiting={str(L['waiting']):<5} closed={str(L['closed']):<5} flags={L['flags']} rounds={L['rounds']} revs={L['revs']}")
        for e in L["events"]:
            print(f"      {e['ts'][5:16]} {e['src']:<5} {e['event']:<12} {e['rev']:<6} {e['by']:>14} → {e['to']:<14} {e['line'][:90]}")

def replay(frm, until=None, quiet_out=False):
    eng = Engine(push=False, replay_from=frm, until=until)
    eng.tick(now=until or now_utc())
    if not quiet_out:
        show(eng.lanes)
    return eng

def run_tests():
    import tempfile
    global FLOWD
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""))
        ok &= bool(cond)

    # T1 permission prompt (synthetic, no tmux, no push)
    tmp = tempfile.mkdtemp()
    open(f"{tmp}/cards.json", "w").write("[]")
    e4 = Engine(office=tmp, push=False)
    keep = FLOWD; FLOWD = tmp
    try:
        t0 = datetime.datetime(2026, 10, 22, 10, 0, tzinfo=UTC)
        pane = "Bash command\n  rm -rf out/tmp\nDo you want to proceed?\n❯ 1. Yes\n  2. No"
        e4.alert(now=t0, send=False)                                          # baseline (empty)
        def at(mins, text):
            t = t0 + datetime.timedelta(minutes=mins)
            first = e4.prompt("S1", "x:@1.%9", t, text=text)
            e4.agents = [{"name": "Tech", "sid": "S1", "status": "busy", "statusAt": 0, "tokens": 0, "ctx": 0, "mtime": t.timestamp(),
                          "prompt": iso(first) if first else None, "ask": None}]
            return e4.alert(now=t, send=False)
        p1, p2, p3, p4 = at(0, pane), at(2, pane), at(3.5, pane), at(4, pane)
        p5 = at(5, "$ ls\nout  work")
        check("T1 no push before 3 min", not p1 and not p2)
        check("T1 one push at 3 min", len(p3) == 1, p3)
        check("T1 not repeated at 4 min", not p4, p4)
        st = jload(f"{tmp}/alerts.json", {})
        check("T1 cleared when the pane changes", not any(k.startswith("prompt") for k in st.get("sent", {})), st)
    finally:
        FLOWD = keep
    # T2 hook signals (synthetic hook files + transcript, no tmux, no push)
    tmp5 = tempfile.mkdtemp(); hd = f"{tmp5}/hooks"; os.makedirs(hd)
    tr = f"{tmp5}/S5.jsonl"
    def line(t):
        open(tr, "a").write(json.dumps({"type": "assistant", "timestamp": t.strftime("%Y-%m-%dT%H:%M:%S.000Z")}) + "\n")
    def hook(ev, t, msg=""):
        json.dump({"event": ev, "ts": t.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"), "message": msg, "cwd": "/x", "transcript": tr},
                  open(f"{hd}/S5.json", "w"))
    t0 = datetime.datetime(2026, 10, 22, 11, 0, tzinfo=UTC)
    m = datetime.timedelta(minutes=1)
    check("T2 no hook file -> None (tmux fallback)", hook_state("S5", hook_signals(hd), tr) is None)
    line(t0); hook("Notification", t0 + 0.1 * m, "Claude needs your permission to use Bash")
    hs = hook_state("S5", hook_signals(hd), tr)
    check("T2 permission notification newer than transcript = waiting", hs and hs["kind"] == "permission" and "Bash" in hs["msg"], hs)
    line(t0 + 2 * m)
    hs = hook_state("S5", hook_signals(hd), tr)
    check("T2 transcript moved on = active", hs and hs["kind"] == "active", hs)
    hook("Stop", t0 + 2 * m)
    hs = hook_state("S5", hook_signals(hd), tr)
    check("T2 Stop = idle", hs and hs["kind"] == "idle", hs)
    hook("Notification", t0 + 3 * m, "Claude is waiting for your input")
    hs = hook_state("S5", hook_signals(hd), tr)
    check("T2 input notification = input (no permission push)", hs and hs["kind"] == "input", hs)
    check("T2 hook from before session start ignored", hook_state("S5", hook_signals(hd), tr, started=(t0 + 10 * m).timestamp()) is None)
    print("ALL PASS" if ok else "SOME FAIL")
    return ok

if __name__ == "__main__":
    a = sys.argv[1:]
    if "--test" in a:
        sys.exit(0 if run_tests() else 1)
    if "--replay" in a:
        frm = parse_utc(a[a.index("--replay") + 1])
        until = parse_utc(a[a.index("--until") + 1]) if "--until" in a else None
        replay(frm, until)
    else:
        print(__doc__)
