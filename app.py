"""
Jio Spares Bot – Python Flask Backend
- Validates users against Active_Users table
- Stores all chat sessions and messages
- Admin dashboard at /admin

Install: pip install flask flask-cors gunicorn
Start:   gunicorn app:app
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

DB_PATH = "jio_spares_bot.db"


# ─────────────────────────────────────────────
# DATABASE INIT
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""

        -- Your existing user master table
        CREATE TABLE IF NOT EXISTS Active_Users (
            Employee_Key   BIGINT PRIMARY KEY,
            Employee_Name  VARCHAR(100) NOT NULL,
            Region         VARCHAR(20),
            State          VARCHAR(35),
            JC_ID          VARCHAR(5),
            Work_Area      VARCHAR(20),
            Work_Stream    VARCHAR(50),
            Position       VARCHAR(50)
        );

        -- Chat session logs
        CREATE TABLE IF NOT EXISTS bot_sessions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id     TEXT    NOT NULL UNIQUE,
            ep_code        TEXT    NOT NULL,
            site_code      TEXT    NOT NULL,
            asi_name       TEXT    NOT NULL,
            region         TEXT,
            state          TEXT,
            start_datetime TEXT    NOT NULL,
            end_datetime   TEXT,
            message_count  INTEGER DEFAULT 0,
            created_at     TEXT    DEFAULT (datetime('now','localtime'))
        );

        -- Individual message logs
        CREATE TABLE IF NOT EXISTS bot_messages (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id     TEXT    NOT NULL,
            role           TEXT    NOT NULL,
            message        TEXT    NOT NULL,
            timestamp      TEXT    NOT NULL,
            created_at     TEXT    DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (session_id) REFERENCES bot_sessions(session_id)
        );

    """)
    conn.commit()
    conn.close()
    print("✅ Database ready:", DB_PATH)


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    conn = get_db()
    user_count = conn.execute("SELECT COUNT(*) as c FROM Active_Users").fetchone()["c"]
    conn.close()
    return jsonify({
        "status": "ok",
        "service": "Jio Spares Bot API",
        "active_users_loaded": user_count,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


# ─────────────────────────────────────────────
# ✅ VALIDATE USER — EP Code + Site Code check
# ─────────────────────────────────────────────

@app.route("/api/validate", methods=["POST", "OPTIONS"])
def validate_user():
    if request.method == "OPTIONS":
        return _cors_preflight()

    data = request.get_json(silent=True) or {}
    ep_code  = str(data.get("ep_code", "")).strip()
    site_code = str(data.get("site_code", "")).strip().upper()

    if not ep_code or not site_code:
        return jsonify({"valid": False, "error": "EP Code and Site Code are required."}), 400

    conn = get_db()
    try:
        # Step 1: Check if EP Code exists at all
        user = conn.execute(
            "SELECT * FROM Active_Users WHERE CAST(Employee_Key AS TEXT) = ?",
            (ep_code,)
        ).fetchone()

        if not user:
            return jsonify({
                "valid": False,
                "error": "❌ User not available. Please check your EP Code."
            })

        # Step 2: EP found — now check if Site Code matches
        if str(user["JC_ID"]).strip().upper() != site_code:
            return jsonify({
                "valid": False,
                "error": "❌ Enter correct site code."
            })

        # Step 3: Both match — return user details
        return jsonify({
            "valid": True,
            "employee_name": user["Employee_Name"],
            "region": user["Region"],
            "state": user["State"],
            "jc_id": user["JC_ID"],
            "work_area": user["Work_Area"],
            "position": user["Position"]
        })

    except Exception as e:
        return jsonify({"valid": False, "error": f"Server error: {str(e)}"}), 500
    finally:
        conn.close()


# ─────────────────────────────────────────────
# SESSION START
# ─────────────────────────────────────────────

@app.route("/api/session/start", methods=["POST", "OPTIONS"])
def session_start():
    if request.method == "OPTIONS":
        return _cors_preflight()

    data = request.get_json(silent=True) or {}
    for field in ["session_id", "ep_code", "site_code", "asi_name"]:
        if not data.get(field):
            return jsonify({"error": f"Missing: {field}"}), 400

    conn = get_db()
    try:
        # Pull extra info from Active_Users to store with session
        user = conn.execute(
            "SELECT Region, State FROM Active_Users WHERE CAST(Employee_Key AS TEXT) = ?",
            (str(data["ep_code"]),)
        ).fetchone()

        conn.execute("""
            INSERT OR IGNORE INTO bot_sessions
                (session_id, ep_code, site_code, asi_name, region, state, start_datetime)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data["session_id"],
            str(data["ep_code"]),
            str(data["site_code"]).upper(),
            str(data["asi_name"]),
            user["Region"] if user else None,
            user["State"]  if user else None,
            data.get("start_datetime", datetime.now().isoformat())
        ))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─────────────────────────────────────────────
# SESSION END
# ─────────────────────────────────────────────

@app.route("/api/session/end", methods=["POST", "OPTIONS"])
def session_end():
    if request.method == "OPTIONS":
        return _cors_preflight()

    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM bot_messages WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        conn.execute("""
            UPDATE bot_sessions SET end_datetime = ?, message_count = ?
            WHERE session_id = ?
        """, (data.get("end_datetime", datetime.now().isoformat()), row["cnt"], session_id))
        conn.commit()
        return jsonify({"success": True, "messages_logged": row["cnt"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─────────────────────────────────────────────
# LOG MESSAGE
# ─────────────────────────────────────────────

@app.route("/api/message", methods=["POST", "OPTIONS"])
def log_message():
    if request.method == "OPTIONS":
        return _cors_preflight()

    data = request.get_json(silent=True) or {}
    for field in ["session_id", "role", "message"]:
        if not data.get(field):
            return jsonify({"error": f"Missing: {field}"}), 400

    if data["role"] not in ("user", "bot"):
        return jsonify({"error": "role must be user or bot"}), 400

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO bot_messages (session_id, role, message, timestamp)
            VALUES (?, ?, ?, ?)
        """, (
            data["session_id"], data["role"],
            str(data["message"]),
            data.get("timestamp", datetime.now().isoformat())
        ))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─────────────────────────────────────────────
# ADMIN DASHBOARD
# ─────────────────────────────────────────────

@app.route("/admin", methods=["GET"])
def admin_dashboard():
    conn = get_db()
    sessions = conn.execute("""
        SELECT s.session_id, s.ep_code, s.site_code, s.asi_name,
               s.region, s.state, s.start_datetime, s.end_datetime,
               COUNT(m.id) as msg_count
        FROM bot_sessions s
        LEFT JOIN bot_messages m ON s.session_id = m.session_id
        GROUP BY s.session_id
        ORDER BY s.start_datetime DESC LIMIT 500
    """).fetchall()

    total_s = conn.execute("SELECT COUNT(*) as c FROM bot_sessions").fetchone()["c"]
    total_m = conn.execute("SELECT COUNT(*) as c FROM bot_messages").fetchone()["c"]
    total_u = conn.execute("SELECT COUNT(DISTINCT ep_code) as c FROM bot_sessions").fetchone()["c"]
    total_au = conn.execute("SELECT COUNT(*) as c FROM Active_Users").fetchone()["c"]
    conn.close()

    rows_html = ""
    for s in sessions:
        s = dict(s)
        end = s["end_datetime"][:16] if s.get("end_datetime") else "<span style='color:#4ade80'>● Active</span>"
        rows_html += f"""
        <tr onclick="window.location='/admin/session/{s['session_id']}'" style="cursor:pointer">
            <td>P{s['ep_code']}</td>
            <td>{s['site_code']}</td>
            <td>{s['asi_name']}</td>
            <td>{s.get('region') or '-'}</td>
            <td>{s.get('state') or '-'}</td>
            <td>{s['start_datetime'][:16]}</td>
            <td>{end}</td>
            <td><span class="badge">{s['msg_count']}</span></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html><head><title>Jio Spares Bot Admin</title><meta charset="UTF-8">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',sans-serif;background:#0d1b2a;color:#e0e0e0;padding:24px}}
  h1{{color:#00b4d8;font-size:22px;margin-bottom:4px}}
  .sub{{color:#555;font-size:12px;margin-bottom:24px}}
  .stats{{display:flex;gap:14px;margin-bottom:24px;flex-wrap:wrap}}
  .stat{{background:#1a2e4a;border:1px solid rgba(0,180,216,0.2);border-radius:12px;padding:16px 24px;text-align:center}}
  .stat-num{{font-size:28px;font-weight:700;color:#00b4d8}}
  .stat-label{{font-size:11px;color:#777;margin-top:3px}}
  table{{width:100%;border-collapse:collapse;background:#1a2e4a;border-radius:12px;overflow:hidden;font-size:13px}}
  th{{background:rgba(0,180,216,0.12);padding:10px 14px;text-align:left;font-size:11px;color:#00b4d8;text-transform:uppercase;letter-spacing:1px}}
  td{{padding:10px 14px;border-bottom:1px solid rgba(255,255,255,0.04)}}
  tr:hover td{{background:rgba(0,180,216,0.05)}}
  .badge{{background:rgba(0,180,216,0.15);color:#00b4d8;border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600}}
  .btn{{display:inline-block;margin-bottom:14px;margin-right:8px;background:rgba(0,180,216,0.12);border:1px solid rgba(0,180,216,0.25);border-radius:8px;padding:7px 16px;color:#00b4d8;font-size:12px;text-decoration:none}}
  .btn:hover{{background:rgba(0,180,216,0.22)}}
</style></head>
<body>
<h1>🤖 Jio Spares Bot – Admin Dashboard</h1>
<div class="sub">Auto-refreshes every 30 seconds</div>
<div class="stats">
  <div class="stat"><div class="stat-num">{total_au}</div><div class="stat-label">Active Users (DB)</div></div>
  <div class="stat"><div class="stat-num">{total_s}</div><div class="stat-label">Total Sessions</div></div>
  <div class="stat"><div class="stat-num">{total_m}</div><div class="stat-label">Total Messages</div></div>
  <div class="stat"><div class="stat-num">{total_u}</div><div class="stat-label">Unique Users</div></div>
</div>
<a class="btn" href="/api/export/sql">⬇ Export SQL</a>
<a class="btn" href="/api/sessions">📄 JSON</a>
<table>
  <thead><tr><th>EP Code</th><th>Site</th><th>Name</th><th>Region</th><th>State</th><th>Start</th><th>End</th><th>Msgs</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<script>setTimeout(()=>location.reload(),30000)</script>
</body></html>"""


# ─────────────────────────────────────────────
# ADMIN SESSION DETAIL
# ─────────────────────────────────────────────

@app.route("/admin/session/<session_id>", methods=["GET"])
def admin_session_detail(session_id):
    conn = get_db()
    s = conn.execute("SELECT * FROM bot_sessions WHERE session_id=?", (session_id,)).fetchone()
    if not s:
        conn.close()
        return "<h2 style='color:white;padding:20px'>Session not found</h2>", 404
    s = dict(s)
    messages = conn.execute(
        "SELECT role, message, timestamp FROM bot_messages WHERE session_id=? ORDER BY timestamp",
        (session_id,)
    ).fetchall()
    conn.close()

    msgs_html = ""
    for m in messages:
        m = dict(m)
        is_user = m["role"] == "user"
        align = "flex-end" if is_user else "flex-start"
        bg    = "rgba(0,180,216,0.18)" if is_user else "#1a2e4a"
        label = f"👤 P{s['ep_code']}" if is_user else "🤖 Bot"
        msgs_html += f"""
        <div style="display:flex;justify-content:{align};margin-bottom:10px">
          <div style="max-width:72%;background:{bg};border-radius:12px;padding:10px 14px">
            <div style="font-size:10px;color:#777;margin-bottom:3px">{label} · {m['timestamp'][11:16]}</div>
            <div style="font-size:13px;line-height:1.6">{m['message'][:600]}</div>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><title>Session Detail</title>
<style>body{{font-family:'Segoe UI',sans-serif;background:#0d1b2a;color:#e0e0e0;padding:24px}}
.meta{{background:#1a2e4a;border-radius:10px;padding:14px 20px;margin:14px 0;font-size:13px;line-height:2}}
a{{color:#00b4d8;text-decoration:none}}h2{{color:#00b4d8}}</style></head>
<body>
<a href="/admin">← Back</a><br><br>
<h2>Session: {session_id}</h2>
<div class="meta">
  <b>EP:</b> P{s['ep_code']} &nbsp;|&nbsp; <b>Site:</b> {s['site_code']} &nbsp;|&nbsp;
  <b>Name:</b> {s['asi_name']} &nbsp;|&nbsp; <b>Region:</b> {s.get('region') or '-'} &nbsp;|&nbsp;
  <b>State:</b> {s.get('state') or '-'}<br>
  <b>Start:</b> {s['start_datetime']} &nbsp;|&nbsp;
  <b>End:</b> {s.get('end_datetime') or 'Still Active'} &nbsp;|&nbsp;
  <b>Messages:</b> {len(messages)}
</div>
{msgs_html}
</body></html>"""


# ─────────────────────────────────────────────
# ALL SESSIONS JSON
# ─────────────────────────────────────────────

@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    conn = get_db()
    rows = conn.execute("""
        SELECT session_id, ep_code, site_code, asi_name, region, state,
               start_datetime, end_datetime, message_count
        FROM bot_sessions ORDER BY start_datetime DESC LIMIT 1000
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────
# EXPORT SQL
# ─────────────────────────────────────────────

@app.route("/api/export/sql", methods=["GET"])
def export_sql():
    conn = get_db()
    sessions = conn.execute("SELECT * FROM bot_sessions ORDER BY start_datetime").fetchall()
    messages = conn.execute("SELECT * FROM bot_messages ORDER BY timestamp").fetchall()
    conn.close()

    lines = [
        f"-- Jio Spares Bot Export | Generated: {datetime.now().isoformat()}", "",
        "CREATE TABLE IF NOT EXISTS bot_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT UNIQUE, ep_code TEXT, site_code TEXT, asi_name TEXT, region TEXT, state TEXT, start_datetime TEXT, end_datetime TEXT, message_count INTEGER);",
        "CREATE TABLE IF NOT EXISTS bot_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, message TEXT, timestamp TEXT);", ""
    ]
    for s in sessions:
        s = dict(s)
        lines.append(f"INSERT INTO bot_sessions (session_id,ep_code,site_code,asi_name,region,state,start_datetime,end_datetime,message_count) VALUES ('{s['session_id']}','{s['ep_code']}','{s['site_code']}','{esc(s['asi_name'])}','{s.get('region') or ''}','{s.get('state') or ''}','{s['start_datetime']}','{s.get('end_datetime') or ''}',{s['message_count']});")
    lines.append("")
    for m in messages:
        m = dict(m)
        lines.append(f"INSERT INTO bot_messages (session_id,role,message,timestamp) VALUES ('{m['session_id']}','{m['role']}','{esc(m['message'])}','{m['timestamp']}');")

    return Response("\n".join(lines), mimetype="text/plain",
                    headers={"Content-Disposition": "attachment; filename=jio_spares_bot_export.sql"})


# ─────────────────────────────────────────────
# UTILS
# ─────────────────────────────────────────────

def esc(s):
    return str(s or "").replace("'", "''")

def _cors_preflight():
    r = Response("", status=204)
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
