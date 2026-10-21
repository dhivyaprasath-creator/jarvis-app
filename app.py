"""JARVIS Personal AI Assistant - Flask backend (SQLite, rule-based + optional AI)."""
import ast, json, operator, os, re, sqlite3, urllib.request
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request
import os

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("JARVIS_DB", os.path.join(BASE, "jarvis.db"))
AI_KEY = os.getenv("AI_API_KEY", "").strip()      # server-side only, never sent to browser
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-6")
KINDS = ("tasks", "notes", "reminders")
app = Flask(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, role TEXT, content TEXT, source TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, text TEXT, done INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, text TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY, text TEXT, due TEXT, done INTEGER DEFAULT 0, notified INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, text TEXT, created TEXT);
"""

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.executescript(SCHEMA)

def now():
    return datetime.now().isoformat(timespec="seconds")

def log(text):
    db().execute("INSERT INTO activity(text,created) VALUES(?,?)", (text, now()))

def rows(sql, args=()):
    return [dict(r) for r in db().execute(sql, args).fetchall()]

# ---------- safe calculator (AST whitelist, no eval) ----------
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}

def _calc(n):
    if isinstance(n, ast.Expression):
        return _calc(n.body)
    if isinstance(n, ast.Constant) and type(n.value) in (int, float):
        return n.value
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = _calc(n.operand)
        return -v if isinstance(n.op, ast.USub) else v
    if isinstance(n, ast.BinOp) and type(n.op) in OPS:
        a, b = _calc(n.left), _calc(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 100:
            raise ValueError("exponent too large")
        return OPS[type(n.op)](a, b)
    raise ValueError("unsupported expression")

def calculate(expr):
    expr = expr.replace("^", "**").replace("÷", "/")
    expr = re.sub(r"(?<=[\d)])\s*[x×]\s*(?=[\d(])", "*", expr)
    try:
        val = _calc(ast.parse(expr.strip(), mode="eval"))
    except ZeroDivisionError:
        return "Division by zero is undefined."
    except Exception:
        return None
    return f"{expr.strip()} = {round(val, 10):g}" if isinstance(val, float) else f"{expr.strip()} = {val}"

# ---------- reminders ----------
def parse_reminder(text):
    due = None
    m = re.search(r"\s+in\s+(\d+)\s*(minutes?|mins?|hours?|hrs?|days?)$", text, re.I)
    if m:
        n, u = int(m.group(1)), m.group(2).lower()
        delta = timedelta(minutes=n) if u.startswith("m") else timedelta(hours=n) if u.startswith("h") else timedelta(days=n)
        due, text = datetime.now() + delta, text[:m.start()]
    else:
        m = re.search(r"\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", text, re.I)
        if m:
            h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
            if ap == "pm" and h < 12: h += 12
            if ap == "am" and h == 12: h = 0
            if h < 24 and mi < 60:
                due = datetime.now().replace(hour=h, minute=mi, second=0, microsecond=0)
                if due <= datetime.now(): due += timedelta(days=1)
                text = text[:m.start()]
    return text.strip(), (due.isoformat(timespec="seconds") if due else None)

HELP = ("I can help with:\n• add task buy milk / list tasks / complete task 3 / delete task 3\n"
        "• note call mom / list notes / delete note 2\n• remind me to stretch in 10 minutes (or at 5pm)\n"
        "• list reminders / delete reminder 1\n• math: 12*(3+4)\n• time, date, help\n"
        "Anything else goes to the AI model only if one is connected.")

def lst(kind, fmt):
    r = rows(f"SELECT * FROM {kind} ORDER BY id")
    return "\n".join(fmt(x) for x in r) if r else f"You have no {kind} yet."

def add(kind, text, extra=None):
    cur = db().execute(f"INSERT INTO {kind}(text,created) VALUES(?,?)", (text[:300], now()))
    log(f"Added {kind[:-1]}: {text[:60]}")
    return cur.lastrowid

def remove(kind, i):
    cur = db().execute(f"DELETE FROM {kind} WHERE id=?", (i,))
    if cur.rowcount:
        log(f"Deleted {kind[:-1]} #{i}")
    return bool(cur.rowcount)

def rule_reply(msg):
    """Return reply string, or None if no rule matched."""
    t = msg.strip(); low = t.lower().rstrip("?!. ")
    if re.match(r"^(hi|hello|hey|good (morning|afternoon|evening))\b", low):
        return "Hello! JARVIS online. Type 'help' to see what I can do."
    if low in ("help", "what can you do", "commands"):
        return HELP
    if re.search(r"\b(thanks|thank you)\b", low):
        return "You're welcome."
    if re.search(r"\bwho are you\b", low):
        return "I'm JARVIS, a local assistant running on your computer."
    if re.search(r"\b(time|date|day|today)\b", low) and len(low.split()) <= 6:
        return datetime.now().strftime("It is %A, %d %B %Y, %I:%M %p.")
    m = re.match(r"^(?:add|new|create)\s+task:?\s+(.+)", t, re.I) or re.match(r"^task:\s*(.+)", t, re.I)
    if m: return f"Task #{add('tasks', m.group(1).strip())} added: {m.group(1).strip()}"
    if re.match(r"^(?:list|show)\s+(?:my\s+)?tasks$", low):
        return lst("tasks", lambda x: f"#{x['id']} [{'x' if x['done'] else ' '}] {x['text']}")
    m = re.match(r"^(?:complete|finish|done)\s+task\s+#?(\d+)$", low)
    if m:
        c = db().execute("UPDATE tasks SET done=1 WHERE id=?", (int(m.group(1)),))
        if c.rowcount: log(f"Completed task #{m.group(1)}")
        return f"Task #{m.group(1)} completed." if c.rowcount else f"No task #{m.group(1)} found."
    m = re.match(r"^(?:add|take|save)?\s*(?:a\s+)?note:?\s+(.+)", t, re.I)
    if m: return f"Note #{add('notes', m.group(1).strip())} saved."
    if re.match(r"^(?:list|show)\s+(?:my\s+)?notes$", low):
        return lst("notes", lambda x: f"#{x['id']} {x['text']}")
    m = re.match(r"^(?:remind me(?: to)?|reminder(?: to)?)\s+(.+)", t, re.I)
    if m:
        text, due = parse_reminder(m.group(1))
        if not text: return "What should I remind you about?"
        c = db().execute("INSERT INTO reminders(text,due,created) VALUES(?,?,?)", (text[:300], due, now()))
        log(f"Added reminder: {text[:60]}")
        when = due.replace("T", " ") if due else "no time set"
        return f"Reminder #{c.lastrowid} set: {text} ({when})."
    if re.match(r"^(?:list|show)\s+(?:my\s+)?reminders$", low):
        return lst("reminders", lambda x: f"#{x['id']} {x['text']} — {(x['due'] or 'no time').replace('T', ' ')}")
    m = re.match(r"^(?:delete|remove)\s+(task|note|reminder)\s+#?(\d+)$", low)
    if m:
        ok = remove(m.group(1) + "s", int(m.group(2)))
        return f"Deleted {m.group(1)} #{m.group(2)}." if ok else f"No {m.group(1)} #{m.group(2)} found."
    m = re.match(r"^(?:calculate|calc|what is|what's|whats)?\s*([\d\s+\-*/().%^x×÷]+)$", low)
    if m and re.search(r"\d", m.group(1)) and re.search(r"[+\-*/%^x×÷]", m.group(1)):
        return calculate(m.group(1)) or "I couldn't evaluate that expression."
    return None

# ---------- optional AI ----------
def ai_reply(history):
    body = json.dumps({"model": AI_MODEL, "max_tokens": 500,
                       "system": "You are JARVIS, a concise, friendly personal assistant.",
                       "messages": history}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": AI_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["content"][0]["text"].strip()

# ---------- routes ----------
@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/state")
def state():
    return jsonify(tasks=rows("SELECT * FROM tasks ORDER BY id DESC"),
                   notes=rows("SELECT * FROM notes ORDER BY id DESC"),
                   reminders=rows("SELECT * FROM reminders ORDER BY id DESC"),
                   activity=rows("SELECT * FROM activity ORDER BY id DESC LIMIT 8"),
                   history=rows("SELECT role,content,source FROM (SELECT * FROM messages ORDER BY id DESC LIMIT 50) ORDER BY id"),
                   ai_connected=bool(AI_KEY))

@app.post("/api/chat")
def chat():
    msg = ((request.get_json(silent=True) or {}).get("message") or "").strip()
    if not msg: return jsonify(error="Please type a message first."), 400
    if len(msg) > 1000: return jsonify(error="Message is too long (max 1000 characters)."), 400
    db().execute("INSERT INTO messages(role,content,created) VALUES('user',?,?)", (msg, now()))
    reply, source = rule_reply(msg), "rules"
    if reply is None:
        if AI_KEY:
            hist = [{"role": r["role"], "content": r["content"]} for r in
                    rows("SELECT role,content FROM (SELECT * FROM messages ORDER BY id DESC LIMIT 10) ORDER BY id")]
            try:
                reply, source = ai_reply(hist), "ai"
            except Exception:
                reply = "The AI service didn't respond (timeout or error). Rule-based commands still work; type 'help'."
        else:
            reply = ("I don't know that one. AI mode is not connected, so I can only handle built-in commands. "
                     "Type 'help' to see them, or set AI_API_KEY in .env.")
    db().execute("INSERT INTO messages(role,content,source,created) VALUES('assistant',?,?,?)", (reply, source, now()))
    db().commit()
    return jsonify(reply=reply, source=source)

@app.post("/api/chat/clear")
def clear_chat():
    db().execute("DELETE FROM messages"); log("Chat history cleared"); db().commit()
    return jsonify(ok=True)

@app.post("/api/<kind>")
def create(kind):
    if kind not in KINDS: return jsonify(error="Not found"), 404
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text: return jsonify(error="Text can't be empty."), 400
    if kind == "reminders":
        text, due = parse_reminder(text)
        db().execute("INSERT INTO reminders(text,due,created) VALUES(?,?,?)", (text[:300], due, now()))
        log(f"Added reminder: {text[:60]}")
    else:
        add(kind, text)
    db().commit()
    return jsonify(ok=True)

@app.post("/api/<kind>/<int:i>/toggle")
def toggle(kind, i):
    if kind not in ("tasks", "reminders"): return jsonify(error="Not found"), 404
    db().execute(f"UPDATE {kind} SET done=1-done WHERE id=?", (i,)); db().commit()
    return jsonify(ok=True)

@app.delete("/api/<kind>/<int:i>")
def delete(kind, i):
    if kind not in KINDS: return jsonify(error="Not found"), 404
    remove(kind, i); db().commit()
    return jsonify(ok=True)

@app.get("/api/reminders/due")
def due():
    r = rows("SELECT * FROM reminders WHERE done=0 AND notified=0 AND due IS NOT NULL AND due<=?", (now(),))
    for x in r:
        db().execute("UPDATE reminders SET notified=1 WHERE id=?", (x["id"],))
    db().commit()
    return jsonify(due=r)

init_db()
if __name__ == "__main__":
    port = int(os.environ.get('PORT',5000))
    app.run(host='0.0.0.0', port=port)
