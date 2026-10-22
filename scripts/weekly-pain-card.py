#!/usr/bin/env python3
"""Weekly (LaunchAgent, e.g. Wednesday 17:30): a card asking the human for 1-2 tasks that felt slow this week.
The answer goes to the coordinator, who passes it to the Tech agent before its tool scout."""
import json, os, datetime
O = os.environ.get("OFFICINA_HOME") or os.path.expanduser("~/.claude/office"); p = f"{O}/cards.json"
try:
    d = json.load(open(p))
except Exception:
    d = []
if not any(c.get("state") == "open" and c.get("kind") == "weekly-pain" for c in d):
    d.append({"id": max([c.get("id", 0) for c in d] + [0]) + 1, "kind": "weekly-pain",
              "q": "1-2 daily tasks that felt slow or annoying this week (one line each)",
              "context": "For the Tech agent's tool scout and build ideas. Type them in the chat.",
              "options": ["I'll type them in the chat", "Nothing this week"], "state": "open", "from": "Tech",
              "at": datetime.datetime.now().strftime("%d/%m %H:%M")})
    json.dump(d, open(p + ".tmp", "w"), indent=1); os.replace(p + ".tmp", p)
