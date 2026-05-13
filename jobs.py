import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from config import config
from names import generate_job_name


JOB_STEPS = [
    ("queued", "Queued"),
    ("downloading_images", "Downloading images"),
    ("review", "Review images"),
    ("downloading_audio", "Extracting audio"),
    ("rendering", "Rendering frames"),
    ("muxing", "Adding audio"),
    ("complete", "Ready"),
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(connect()) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    status TEXT NOT NULL,
                    step TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    board_url TEXT NOT NULL,
                    youtube_url TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    frame_rate INTEGER NOT NULL,
                    output_path TEXT,
                    saved INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "saved" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN saved INTEGER NOT NULL DEFAULT 0")
            if "name" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN name TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS image_blocklist (
                    checksum TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
                """
            )


def job_dir(job_id):
    return config.output_dir / job_id


def create_job(data):
    init_db()
    job_id = uuid.uuid4().hex[:12]
    name = generate_job_name(job_id)
    now = utc_now()
    frame_rate = data.get("frame_rate") or config.default_frame_rate
    with closing(connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, name, status, step, progress, board_url, youtube_url, start_time,
                    end_time, frame_rate, details, created_at, updated_at
                )
                VALUES (?, ?, 'queued', 'queued', 0, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    job_id,
                    name,
                    data["board_url"],
                    data["youtube_url"],
                    data["start_time"],
                    data["end_time"],
                    frame_rate,
                    now,
                    now,
                ),
            )
    job_dir(job_id).mkdir(parents=True, exist_ok=True)
    return job_id


def _row_to_job(row):
    if row is None:
        return None
    job = dict(row)
    if not job.get("name"):
        job["name"] = generate_job_name(job["id"])
    job["details"] = json.loads(job.get("details") or "{}")
    job["download_url"] = f"/download/{job['id']}" if job.get("output_path") else None
    job["video_url"] = f"/video/{job['id']}" if job.get("output_path") else None
    job["open_url"] = f"/open/{job['id']}" if job.get("output_path") else None
    job["save_url"] = f"/save/{job['id']}" if job.get("output_path") else None
    return job


def get_job(job_id):
    init_db()
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row)


def recent_jobs(limit=8):
    init_db()
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def update_job(job_id, *, status=None, step=None, progress=None, output_path=None, error=None, details=None):
    fields = ["updated_at = ?"]
    values = [utc_now()]

    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if step is not None:
        fields.append("step = ?")
        values.append(step)
    if progress is not None:
        fields.append("progress = ?")
        values.append(progress)
    if output_path is not None:
        fields.append("output_path = ?")
        values.append(str(output_path))
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if details is not None:
        fields.append("details = ?")
        values.append(json.dumps(details))
    if status in {"complete", "failed"}:
        fields.append("completed_at = ?")
        values.append(utc_now())

    values.append(job_id)
    with closing(connect()) as conn:
        with conn:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)


def mark_saved(job_id):
    with closing(connect()) as conn:
        with conn:
            conn.execute("UPDATE jobs SET saved = 1, updated_at = ? WHERE id = ?", (utc_now(), job_id))


def block_checksums(checksums):
    now = utc_now()
    with closing(connect()) as conn:
        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO image_blocklist (checksum, created_at) VALUES (?, ?)",
                [(checksum, now) for checksum in checksums],
            )


def blocked_checksums():
    init_db()
    with closing(connect()) as conn:
        rows = conn.execute("SELECT checksum FROM image_blocklist").fetchall()
    return {row["checksum"] for row in rows}


def cleanup_unsaved_outputs(except_job_id=None):
    init_db()
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT id, output_path FROM jobs WHERE saved = 0 AND output_path IS NOT NULL AND id != ?",
            (except_job_id or "",),
        ).fetchall()
        with conn:
            for row in rows:
                path = Path(row["output_path"])
                if path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        continue
                conn.execute("UPDATE jobs SET output_path = NULL, updated_at = ? WHERE id = ?", (utc_now(), row["id"]))


def step_payload(active_step):
    active_index = next((idx for idx, item in enumerate(JOB_STEPS) if item[0] == active_step), 0)
    return [
        {
            "id": step_id,
            "label": label,
            "state": "done" if idx < active_index else "active" if idx == active_index else "waiting",
        }
        for idx, (step_id, label) in enumerate(JOB_STEPS)
    ]


def output_path_for(job_id):
    return Path(job_dir(job_id) / "output.mp4")
