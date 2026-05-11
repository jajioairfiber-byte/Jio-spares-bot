"""
Jio Spares Bot – Python Flask Backend
Handles session logging to SQLite database.
Deploy on Render.com (free tier) for persistent SQL storage.

Install: pip install flask flask-cors
Run:     python app.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Allow all origins (so GitHub Pages frontend can connect)

DB_PATH = "jio_spares_bot.db"

# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS bot_sessions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    TEXT    NOT NULL UNIQUE,
            ep_code       TEXT    NOT NULL,
            site_code     TEXT    NOT NULL,
            asi_name      TEXT    NOT NULL,
            start_datetime TEXT   NOT NULL,
            end_datetime  TEXT,
            message_count INTEGER DEFAULT 0,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS bot_messages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    TEXT    NOT NULL,
            role          TEXT    NOT NULL CHECK(role IN ('user','bot')),
            message       TEXT    NOT NULL,
            timestamp     TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES bot_sessions(session_id)
        );
    """)

    conn.commit()
    conn.close()
    print("✅ Database initialized:", DB_PATH)

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Jio Spares Bot API", "time": datetime.now().isoformat()})


@app.route("/api/session/start", methods=["POST"])
def session_start():
    """Called when user logs in and starts a chat session."""
    data = request.get_json()

    required = ["session_id", "ep_code", "site_code", "asi_name"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing field: {field}"}), 400

    # Validate: ep_code must be numeric (no "P")
    if not str(data["ep_code"]).isdigit():
        return jsonify({"error": "EP code must be numeric without 'P' prefix"}), 400

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO bot_sessions (session_id, ep_code, site_code, asi_name, start_datetime)
            VALUES (?, ?, ?, ?, ?)
        """, (
            data["session_id"],
            data["ep_code"],
            data["site_code"].upper(),
            data["asi_name"],
            data.get("start_datetime", datetime.now().isoformat())
        ))
        conn.commit()
        return jsonify({"success": True, "session_id": data["session_id"]})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Session ID already exists"}), 409
    finally:
        conn.close()


@app.route("/api/session/end", methods=["POST"])
def session_end():
    """Called when the user ends the chat session."""
    data = request.get_json()
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = get_db()
    try:
        # Count messages for this session
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM bot_messages WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        msg_count = row["cnt"] if row else 0

        conn.execute("""
            UPDATE bot_sessions
            SET end_datetime = ?, message_count = ?
            WHERE session_id = ?
        """, (
            data.get("end_datetime", datetime.now().isoformat()),
            msg_count,
            session_id
        ))
        conn.commit()
        return jsonify({"success": True, "messages_logged": msg_count})
    finally:
        conn.close()


@app.route("/api/message", methods=["POST"])
def log_message():
    """Log a single chat message (user or bot)."""
    data = request.get_json()

    required = ["session_id", "role", "message"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing field: {field}"}), 400

    if data["role"] not in ("user", "bot"):
        return jsonify({"error": "role must be 'user' or 'bot'"}), 400

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO bot_messages (session_id, role, message, timestamp)
            VALUES (?, ?, ?, ?)
        """, (
            data["session_id"],
            data["role"],
            data["message"],
            data.get("timestamp", datetime.now().isoformat())
        ))
        conn.commit()
        return jsonify({"success": True})
    finally:
        conn.close()


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    """Admin: list all sessions with summary."""
    conn = get_db()
    rows = conn.execute("""
        SELECT s.session_id, s.ep_code, s.site_code, s.asi_name,
               s.start_datetime, s.end_datetime, s.message_count
        FROM bot_sessions s
        ORDER BY s.start_datetime DESC
        LIMIT 500
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    """Admin: get full session with messages."""
    conn = get_db()
    session = conn.execute(
        "SELECT * FROM bot_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()

    if not session:
        conn.close()
        return jsonify({"error": "Session not found"}), 404

    messages = conn.execute(
        "SELECT role, message, timestamp FROM bot_messages WHERE session_id = ? ORDER BY timestamp",
        (session_id,)
    ).fetchall()

    conn.close()
    return jsonify({
        "session": dict(session),
        "messages": [dict(m) for m in messages]
    })


@app.route("/api/export/sql", methods=["GET"])
def export_sql():
    """Export all data as SQL INSERT statements."""
    conn = get_db()
    sessions = conn.execute("SELECT * FROM bot_sessions ORDER BY start_datetime").fetchall()
    messages = conn.execute("SELECT * FROM bot_messages ORDER BY timestamp").fetchall()
    conn.close()

    lines = [
        "-- Jio Spares Bot SQL Export",
        f"-- Generated: {datetime.now().isoformat()}",
        "",
        "CREATE TABLE IF NOT EXISTS bot_sessions (",
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,",
        "  session_id TEXT NOT NULL UNIQUE,",
        "  ep_code TEXT NOT NULL,",
        "  site_code TEXT NOT NULL,",
        "  asi_name TEXT NOT NULL,",
        "  start_datetime TEXT NOT NULL,",
        "  end_datetime TEXT,",
        "  message_count INTEGER DEFAULT 0",
        ");",
        "",
        "CREATE TABLE IF NOT EXISTS bot_messages (",
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,",
        "  session_id TEXT NOT NULL,",
        "  role TEXT NOT NULL,",
        "  message TEXT NOT NULL,",
        "  timestamp TEXT NOT NULL",
        ");",
        ""
    ]

    for s in sessions:
        s = dict(s)
        lines.append(
            f"INSERT INTO bot_sessions (session_id, ep_code, site_code, asi_name, start_datetime, end_datetime, message_count) "
            f"VALUES ('{s['session_id']}', '{s['ep_code']}', '{s['site_code']}', '{esc(s['asi_name'])}', "
            f"'{s['start_datetime']}', '{s.get('end_datetime') or ''}', {s['message_count']});"
        )

    lines.append("")
    for m in messages:
        m = dict(m)
        lines.append(
            f"INSERT INTO bot_messages (session_id, role, message, timestamp) "
            f"VALUES ('{m['session_id']}', '{m['role']}', '{esc(m['message'])}', '{m['timestamp']}');"
        )

    from flask import Response
    return Response("\n".join(lines), mimetype="text/plain",
                    headers={"Content-Disposition": "attachment; filename=jio_spares_bot_export.sql"})


def esc(s):
    return str(s or "").replace("'", "''")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Jio Spares Bot API running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
