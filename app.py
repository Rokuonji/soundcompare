import os
import json
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, send_from_directory, abort
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    String,
    Text,
    DateTime,
)
from sqlalchemy.sql import select

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required (Render Postgres URL)")

ADMIN_CODE = os.environ.get("ADMIN_CODE", "admin123")

app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")

# --- Database setup (SQLAlchemy + Postgres) ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
metadata = MetaData()

submissions = Table(
    "submissions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("submission_id", String(255), nullable=False),
    Column("seed", Integer, nullable=False),
    Column("timestamp_start", String(64), nullable=False),
    Column("timestamp_end", String(64), nullable=False),
    Column("duration_seconds", Integer, nullable=False),
    Column("answers_json", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)


def init_db():
    # Create tables if they do not exist
    metadata.create_all(engine)
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

    with engine.begin() as conn:
        conn.execute(
            submissions.insert().values(
                submission_id=data["submissionId"],
                seed=int(data["seed"]),
                timestamp_start=str(data["timestampStart"]),
                timestamp_end=str(data["timestampEnd"]),
                duration_seconds=int(data["durationSeconds"]),
                answers_json=json.dumps(data["answers"], ensure_ascii=False),
                created_at=datetime.utcnow(),
            )
        )

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

    with engine.connect() as conn:
        rows = conn.execute(select(submissions).order_by(submissions.c.id.asc())).fetchall()

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
                "createdAt": r["created_at"].isoformat() if r["created_at"] else None,
                "answers": answers,
            }
        )

    return jsonify(result)


@app.route("/api/admin-clear", methods=["POST"])
def api_admin_clear():
    require_admin_code_from_json()

    with engine.begin() as conn:
        conn.execute(submissions.delete())

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
    with engine.begin() as conn:
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
                submissions.insert().values(
                    submission_id=f"test-{i + 1}-{int(start.timestamp())}",
                    seed=rand_int(1, 2**32 - 1),
                    timestamp_start=start.isoformat() + "Z",
                    timestamp_end=end.isoformat() + "Z",
                    duration_seconds=duration_seconds,
                    answers_json=json.dumps(answers, ensure_ascii=False),
                    created_at=datetime.utcnow(),
                )
            )

    return jsonify({"status": "generated", "count": total})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
