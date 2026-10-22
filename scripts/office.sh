#!/bin/bash
# Post to Officina from any agent (or by hand). Set OFFICE_AGENT="<your name>" so the entry shows who wrote it.
#   office.sh artifact "<title>" "<url or ->" "<package>" "<status>" "<local path>"
#   office.sh task "<title>" "<owner>" "<topic>" [doing|waiting]
#   office.sh done "<task title contains>"
#   office.sh card "<question>" "<option 1|option 2|...>" ["context"]   a question card for the human (answer comes back to the coordinator)
#   office.sh draft "<title>" "<plain text>"          a copy-ready draft (message, mail, command); the human sends it
#   office.sh view "<local file path>" ["<title>"] ["name1,name2" focus] ['{"pos":[x,y,z],"target":[x,y,z]}']   open in the viewer
#   office.sh compare "<new.pdf>" "<old.pdf>"         PDF revision compare
#   office.sh flow <submit|change|pass|file|filed|to-human|sent|reopen> "<deliverable key>" [REV##] ["note"]   flow-lane event
#   office.sh request "<what the human could do so I work better>" ["context"]   Requests page; the answer comes back via the coordinator
. "$(dirname "$0")/_env.sh"
python3 - "$OFFICINA_HOME" "$PORT" "$COORD" "$(cfg human_name You)" "$@" <<'PY'
import json, sys, os, datetime, time, urllib.request
O, PORT, COORD, HUMAN = sys.argv[1:5]; a = sys.argv[5:]
if not a:
    print("usage: office.sh <artifact|task|done|card|draft|view|compare|flow|request> ...  (see the comments at the top)"); sys.exit(1)
def L(f, d=None):
    try: return json.load(open(f"{O}/{f}"))
    except Exception: return [] if d is None else d
def S(f, d):
    json.dump(d, open(f"{O}/{f}.tmp", "w"), indent=1, ensure_ascii=False); os.replace(f"{O}/{f}.tmp", f"{O}/{f}")
def post(path, body):
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode(), method="POST"), timeout=5)
    return r.read().decode()[:200]
who = os.environ.get("OFFICE_AGENT", "")
c = a[0]
if c == "artifact":
    d = L("artifacts.json"); d.insert(0, {"date": datetime.date.today().isoformat(), "title": a[1], "url": a[2] if len(a) > 2 else "",
        "pkg": a[3] if len(a) > 3 else "", "status": a[4] if len(a) > 4 else "filed", "path": a[5] if len(a) > 5 else ""}); S("artifacts.json", d[:500])
elif c == "task":
    d = L("tasks.json"); owner = a[2] if len(a) > 2 else COORD
    d.append({"id": max([t["id"] for t in d] + [0]) + 1, "title": a[1], "owner": owner, "topic": a[3] if len(a) > 3 else "",
              "state": a[4] if len(a) > 4 else ("waiting" if owner == HUMAN else "doing"), "updated": datetime.datetime.now().strftime("%d/%m %H:%M")}); S("tasks.json", d)
elif c == "done":
    d = L("tasks.json"); k = a[1].lower()
    for t in d:
        if k in t["title"].lower() and t["state"] != "done": t["state"] = "done"; t["doneAt"] = datetime.datetime.now().strftime("%d/%m %H:%M")
    S("tasks.json", d)
elif c == "card":
    d = L("cards.json")
    d.append({"id": max([x.get("id", 0) for x in d] + [0]) + 1, "q": a[1], "options": [o.strip() for o in (a[2] if len(a) > 2 else "Yes|No").split("|")],
              "context": a[3] if len(a) > 3 else "", "state": "open", "from": who or COORD, "at": datetime.datetime.now().strftime("%d/%m %H:%M")}); S("cards.json", d)
elif c == "draft":
    print(post("/api/drafts", {"op": "add", "title": a[1], "text": a[2]})); sys.exit(0)
elif c == "view":
    print(post("/api/view", {"path": os.path.abspath(a[1]), "title": a[2] if len(a) > 2 and a[2] else None,
                              "focus": a[3].split(",") if len(a) > 3 and a[3] else None, "camera": json.loads(a[4]) if len(a) > 4 and a[4] else None})); sys.exit(0)
elif c == "compare":
    print(post("/api/view", {"path": os.path.abspath(a[1]), "old": os.path.abspath(a[2])})); sys.exit(0)
elif c == "flow":
    ev = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": a[1], "key": a[2] if len(a) > 2 else "", "rev": a[3] if len(a) > 3 else "",
          "note": a[4] if len(a) > 4 else "", "by": who}
    open(f"{O}/flow.jsonl", "a").write(json.dumps(ev, ensure_ascii=False) + "\n")
elif c == "request":
    d = L("requests.json")
    d.append({"id": int(time.time() * 1000), "from": who or "unknown", "text": a[1], "context": a[2] if len(a) > 2 else "",
              "at": time.strftime("%Y-%m-%d %H:%M"), "state": "open", "reply": "", "replyAt": ""}); S("requests.json", d)
else:
    print("unknown command:", c); sys.exit(1)
print("ok")
PY
