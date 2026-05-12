"""
Jio Spares Bot – Flask Backend with MySQL
Credentials are loaded from Render Environment Variables.
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import mysql.connector
import os
from datetime import datetime

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})


# ─────────────────────────────────────────────
# MySQL CONNECTION — reads from ENV variables
# ─────────────────────────────────────────────

def get_db():
    return mysql.connector.connect(
        host     = os.environ.get("MYSQL_HOST"),
        port     = int(os.environ.get("MYSQL_PORT", 3306)),
        database = os.environ.get("MYSQL_DATABASE"),
        user     = os.environ.get("MYSQL_USER"),
        password = os.environ.get("MYSQL_PASSWORD"),
        connect_timeout = 10
    )


def init_db():
    """Create bot tables if they don't exist (active_users already exists in your MySQL)."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_sessions (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            session_id     VARCHAR(50)  NOT NULL UNIQUE,
            ep_code        VARCHAR(20)  NOT NULL,
            site_code      VARCHAR(10)  NOT NULL,
            asi_name       VARCHAR(100) NOT NULL,
            region         VARCHAR(50),
            state          VARCHAR(50),
            start_datetime DATETIME     NOT NULL,
            end_datetime   DATETIME,
            message_count  INT          DEFAULT 0,
            created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_messages (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            session_id     VARCHAR(50)  NOT NULL,
            role           VARCHAR(10)  NOT NULL,
            message        TEXT         NOT NULL,
            timestamp      DATETIME     NOT NULL,
            created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES bot_sessions(session_id)
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("✅ MySQL tables ready")


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM active_users")
        user_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return jsonify({
            "status"               : "ok",
            "service"              : "Jio Spares Bot API",
            "active_users_loaded"  : user_count,
            "time"                 : datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────
# ✅ VALIDATE USER
# ─────────────────────────────────────────────

@app.route("/api/validate", methods=["POST", "OPTIONS"])
def validate_user():
    if request.method == "OPTIONS":
        return _cors_preflight()

    data      = request.get_json(silent=True) or {}
    ep_code   = str(data.get("ep_code",   "")).strip()
    site_code = str(data.get("site_code", "")).strip().upper()

    if not ep_code or not site_code:
        return jsonify({"valid": False, "error": "EP Code and Site Code are required."}), 400

    try:
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)

        # Step 1 — Check if EP Code exists
        cursor.execute(
            "SELECT * FROM active_users WHERE CAST(Employee_Key AS CHAR) = %s",
            (ep_code,)
        )
        user = cursor.fetchone()

        if not user:
            cursor.close()
            conn.close()
            return jsonify({
                "valid" : False,
                "error" : "❌ User not available. Please check your EP Code."
            })

        # Step 2 — Check if Site Code matches
        if str(user["JC_ID"]).strip().upper() != site_code:
            cursor.close()
            conn.close()
            return jsonify({
                "valid" : False,
                "error" : "❌ Enter correct site code."
            })

        cursor.close()
        conn.close()

        # Both match ✅
        return jsonify({
            "valid"         : True,
            "employee_name" : user["Employee_Name"],
            "region"        : user["Region"],
            "state"         : user["State"],
            "jc_id"         : user["JC_ID"],
            "work_area"     : user["Work_Area"],
            "position"      : user["Position"]
        })

    except Exception as e:
        return jsonify({"valid": False, "error": f"Server error: {str(e)}"}), 500


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

    try:
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get region/state from active_users
        cursor.execute(
            "SELECT Region, State FROM active_users WHERE CAST(Employee_Key AS CHAR) = %s",
            (str(data["ep_code"]),)
        )
        user = cursor.fetchone()

        cursor.execute("""
            INSERT IGNORE INTO bot_sessions
                (session_id, ep_code, site_code, asi_name, region, state, start_datetime)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
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
        cursor.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# SESSION END
# ─────────────────────────────────────────────

@app.route("/api/session/end", methods=["POST", "OPTIONS"])
def session_end():
    if request.method == "OPTIONS":
        return _cors_preflight()

    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    try:
        conn   = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM bot_messages WHERE session_id = %s", (session_id,)
        )
        msg_count = cursor.fetchone()[0]

        cursor.execute("""
            UPDATE bot_sessions
            SET end_datetime = %s, message_count = %s
            WHERE session_id = %s
        """, (
            data.get("end_datetime", datetime.now().isoformat()),
            msg_count,
            session_id
        ))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True, "messages_logged": msg_count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bot_messages (session_id, role, message, timestamp)
            VALUES (%s, %s, %s, %s)
        """, (
            data["session_id"],
            data["role"],
            str(data["message"]),
            data.get("timestamp", datetime.now().isoformat())
        ))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# ADMIN DASHBOARD
# ─────────────────────────────────────────────

@app.route("/admin", methods=["GET"])
def admin_dashboard():
    try:
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT s.session_id, s.ep_code, s.site_code, s.asi_name,
                   s.region, s.state, s.start_datetime, s.end_datetime,
                   COUNT(m.id) as msg_count
            FROM bot_sessions s
            LEFT JOIN bot_messages m ON s.session_id = m.session_id
            GROUP BY s.session_id
            ORDER BY s.start_datetime DESC LIMIT 500
        """)
        sessions = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) as c FROM bot_sessions")
        total_s = cursor.fetchone()["c"]
        cursor.execute("SELECT COUNT(*) as c FROM bot_messages")
        total_m = cursor.fetchone()["c"]
        cursor.execute("SELECT COUNT(DISTINCT ep_code) as c FROM bot_sessions")
        total_u = cursor.fetchone()["c"]
        cursor.execute("SELECT COUNT(*) as c FROM active_users")
        total_au = cursor.fetchone()["c"]

        cursor.close()
        conn.close()

        rows_html = ""
        for s in sessions:
            end = str(s["end_datetime"])[:16] if s.get("end_datetime") else "<span style='color:#4ade80'>● Active</span>"
            rows_html += f"""
            <tr onclick="window.location='/admin/session/{s['session_id']}'" style="cursor:pointer">
                <td>P{s['ep_code']}</td>
                <td>{s['site_code']}</td>
                <td>{s['asi_name']}</td>
                <td>{s.get('region') or '-'}</td>
                <td>{s.get('state') or '-'}</td>
                <td>{str(s['start_datetime'])[:16]}</td>
                <td>{end}</td>
                <td><span class="badge">{s['msg_count']}</span></td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html><head><title>Jio Spares Bot Admin</title><meta charset="UTF-8">
<meta http-equiv="refresh" content="30">
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
  <div class="stat"><div class="stat-num">{total_au}</div><div class="stat-label">Active Users (MySQL)</div></div>
  <div class="stat"><div class="stat-num">{total_s}</div><div class="stat-label">Total Sessions</div></div>
  <div class="stat"><div class="stat-num">{total_m}</div><div class="stat-label">Total Messages</div></div>
  <div class="stat"><div class="stat-num">{total_u}</div><div class="stat-label">Unique Users</div></div>
</div>
<a class="btn" href="/api/sessions">📄 JSON Export</a>
<table>
  <thead><tr><th>EP Code</th><th>Site</th><th>Name</th><th>Region</th><th>State</th><th>Start</th><th>End</th><th>Msgs</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</body></html>"""

    except Exception as e:
        return f"<h2 style='color:red;padding:20px'>DB Error: {str(e)}</h2>", 500


# ─────────────────────────────────────────────
# SESSION DETAIL
# ─────────────────────────────────────────────

@app.route("/admin/session/<session_id>", methods=["GET"])
def admin_session_detail(session_id):
    try:
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM bot_sessions WHERE session_id=%s", (session_id,))
        s = cursor.fetchone()
        if not s:
            conn.close()
            return "<h2 style='color:white;padding:20px'>Session not found</h2>", 404

        cursor.execute(
            "SELECT role, message, timestamp FROM bot_messages WHERE session_id=%s ORDER BY timestamp",
            (session_id,)
        )
        messages = cursor.fetchall()
        cursor.close()
        conn.close()

        msgs_html = ""
        for m in messages:
            is_user = m["role"] == "user"
            align   = "flex-end"  if is_user else "flex-start"
            bg      = "rgba(0,180,216,0.18)" if is_user else "#1a2e4a"
            label   = f"👤 P{s['ep_code']}" if is_user else "🤖 Bot"
            msgs_html += f"""
            <div style="display:flex;justify-content:{align};margin-bottom:10px">
              <div style="max-width:72%;background:{bg};border-radius:12px;padding:10px 14px">
                <div style="font-size:10px;color:#777;margin-bottom:3px">{label} · {str(m['timestamp'])[11:16]}</div>
                <div style="font-size:13px;line-height:1.6">{str(m['message'])[:800]}</div>
              </div>
            </div>"""

        return f"""<!DOCTYPE html>
<html><head><title>Session Detail</title>
<style>body{{font-family:'Segoe UI',sans-serif;background:#0d1b2a;color:#e0e0e0;padding:24px}}
.meta{{background:#1a2e4a;border-radius:10px;padding:14px 20px;margin:14px 0;font-size:13px;line-height:2}}
a{{color:#00b4d8;text-decoration:none}}h2{{color:#00b4d8}}</style></head>
<body>
<a href="/admin">← Back to Dashboard</a><br><br>
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

    except Exception as e:
        return f"<h2 style='color:red;padding:20px'>Error: {str(e)}</h2>", 500


# ─────────────────────────────────────────────
# ALL SESSIONS JSON
# ─────────────────────────────────────────────

@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    try:
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT session_id, ep_code, site_code, asi_name, region, state,
                   start_datetime, end_datetime, message_count
            FROM bot_sessions ORDER BY start_datetime DESC LIMIT 1000
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        # Convert datetime to string for JSON
        for r in rows:
            for k in ["start_datetime", "end_datetime", "created_at"]:
                if r.get(k):
                    r[k] = str(r[k])
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# UTILS
# ─────────────────────────────────────────────

def _cors_preflight():
    r = Response("", status=204)
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)

init_db()
