import os
import json
import sqlite3
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory, abort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "experiment.db"))
ADMIN_CODE = os.environ.get("ADMIN_CODE", "admin123")

app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id TEXT,
            seed INTEGER,
            timestamp_start TEXT,
            timestamp_end TEXT,
            duration_seconds INTEGER,
            answers_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    conn.close()


@app.route("/")
def index():
    # Serve the start page
    return send_from_directory(BASE_DIR, "START.html")


@app.route("/api/submit", methods=["POST"])
def api_submit():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    required_fields = ["submissionId", "seed", "timestampStart", "timestampEnd", "durationSeconds", "answers"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400

    # Basic validation of answers structure
    if not isinstance(data.get("answers"), list):
        return jsonify({"error": "answers must be a list"}), 400

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO submissions (
                submission_id, seed, timestamp_start, timestamp_end,
                duration_seconds, answers_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data["submissionId"],
                int(data["seed"]),
                str(data["timestampStart"]),
                str(data["timestampEnd"]),
                int(data["durationSeconds"]),
                json.dumps(data["answers"], ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"status": "ok"})


def require_admin_code_from_query():
    code = request.args.get("code")
    if not code or code != ADMIN_CODE:
        abort(403)


def require_admin_code_from_json():
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    if not code or code != ADMIN_CODE:
        abort(403)
    return data


@app.route("/api/admin-data", methods=["GET"])
def api_admin_data():
    require_admin_code_from_query()

    conn = get_db()
    try:
        cur = conn.execute(
            """
            SELECT
                id,
                submission_id,
                seed,
                timestamp_start,
                timestamp_end,
                duration_seconds,
                answers_json,
                created_at
            FROM submissions
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for r in rows:
        try:
            answers = json.loads(r["answers_json"]) if r["answers_json"] else []
        except Exception:
            answers = []
        result.append(
            {
                "id": r["id"],
                "submissionId": r["submission_id"],
                "seed": r["seed"],
                "timestampStart": r["timestamp_start"],
                "timestampEnd": r["timestamp_end"],
                "durationSeconds": r["duration_seconds"],
                "createdAt": r["created_at"],
                "answers": answers,
            }
        )

    return jsonify(result)


@app.route("/api/admin-clear", methods=["POST"])
def api_admin_clear():
    require_admin_code_from_json()

    conn = get_db()
    try:
        conn.execute("DELETE FROM submissions")
        conn.commit()
    finally:
        conn.close()

    return jsonify({"status": "cleared"})


@app.route("/api/admin-generate-test", methods=["POST"])
def api_admin_generate_test():
    data = require_admin_code_from_json()

    total = int(data.get("count", 5))
    total_comparisons = 15

    def rand_int(min_v, max_v):
        import random

        return random.randint(min_v, max_v)

    now = datetime.utcnow()
    conn = get_db()
    try:
        for i in range(total):
            start = now
            duration_seconds = rand_int(60, 600)
            end = start + timedelta(seconds=duration_seconds)

            answers = []
            for j in range(total_comparisons):
                answers.append(
                    {
                        "comparison": j + 1,
                        "audio1": f"Audio_{j + 1}_A.wav",
                        "audio2": f"Audio_{j + 1}_B.wav",
                        "answer": rand_int(0, 2),
                    }
                )

            conn.execute(
                """
                INSERT INTO submissions (
                    submission_id, seed, timestamp_start, timestamp_end,
                    duration_seconds, answers_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"test-{i + 1}-{int(start.timestamp())}",
                    rand_int(1, 2**32 - 1),
                    start.isoformat() + "Z",
                    end.isoformat() + "Z",
                    duration_seconds,
                    json.dumps(answers, ensure_ascii=False),
                ),
            )

        conn.commit()
    finally:
        conn.close()

    return jsonify({"status": "generated", "count": total})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
