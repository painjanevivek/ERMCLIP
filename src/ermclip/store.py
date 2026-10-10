from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
import uuid

from .models import JobSpec


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, dedupe TEXT UNIQUE NOT NULL, spec TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', stage TEXT NOT NULL DEFAULT 'queued',
 attempts INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL,
 available REAL NOT NULL DEFAULT 0, cancel INTEGER NOT NULL DEFAULT 0,
 error TEXT, output TEXT, checkpoint TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, job_id TEXT, time REAL NOT NULL, kind TEXT NOT NULL,
 payload TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0, delivery_attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS controls (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback (
 id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, clip TEXT NOT NULL,
 rating INTEGER NOT NULL, notes TEXT NOT NULL, time REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS watched (path TEXT PRIMARY KEY, fingerprint TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS job_ready ON jobs(status, available, created);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def submit(self, spec: JobSpec, dedupe: str):
        now = time.time()
        with self.connect() as db:
            job_id = uuid.uuid4().hex[:16]
            cursor = db.execute("INSERT OR IGNORE INTO jobs(id,dedupe,spec,created,updated) VALUES (?,?,?,?,?)",
                               (job_id, dedupe, spec.model_dump_json(), now, now))
            created = cursor.rowcount == 1
            row = db.execute("SELECT id FROM jobs WHERE dedupe=?", (dedupe,)).fetchone()
            job_id = row["id"]
            if created:
                db.execute("INSERT INTO events(job_id,time,kind,payload) VALUES (?,?,?,?)",
                           (job_id, now, "accepted", json.dumps({"source":spec.source})))
        return job_id, created

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Unknown job ID")
        result = dict(row)
        result["spec"] = json.loads(result["spec"])
        result["checkpoint"] = json.loads(result["checkpoint"])
        return result

    def list(self, limit=50):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,status,stage,attempts,created,updated,error,output FROM jobs ORDER BY created DESC LIMIT ?", (limit,))]

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pause = db.execute("SELECT value FROM controls WHERE key='pause' ").fetchone()
            if pause and pause[0] == "1":
                return None
            row = db.execute("SELECT id FROM jobs WHERE status IN ('queued','retry') AND available <= ? AND cancel=0 ORDER BY created LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running', attempts=attempts+1, updated=? WHERE id=?", (time.time(), row[0]))
        return self.get(row[0])

    def update(self, job_id, **fields):
        allowed = {"status", "stage", "error", "output", "checkpoint", "available", "cancel"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid job update")
        if "checkpoint" in fields:
            fields["checkpoint"] = json.dumps(fields["checkpoint"])
        fields["updated"] = time.time()
        with self.connect() as db:
            db.execute("UPDATE jobs SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?", (*fields.values(), job_id))

    def event(self, job_id, kind, payload):
        with self.connect() as db:
            db.execute("INSERT INTO events(job_id,time,kind,payload) VALUES (?,?,?,?)", (job_id, time.time(), kind, json.dumps(payload)))

    def control(self, key, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute("INSERT INTO controls VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
            row = db.execute("SELECT value FROM controls WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def cancel(self, job_id):
        job = self.get(job_id)
        if job["status"] in ("completed", "review_required", "no_matches", "failed", "cancelled"):
            return
        self.update(job_id, cancel=1, **({"status":"cancelled"} if job["status"] != "running" else {}))

    def recover(self):
        # Called only after the exclusive worker lock is acquired.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=CASE WHEN cancel=1 THEN 'cancelled' ELSE 'queued' END, updated=? WHERE status='running'", (time.time(),))

    def feedback(self, job_id, clip, rating, notes):
        self.get(job_id)
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")
        with self.connect() as db:
            db.execute("INSERT INTO feedback(job_id,clip,rating,notes,time) VALUES (?,?,?,?,?)", (job_id, clip, rating, notes, time.time()))

    def preferences(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM feedback ORDER BY time DESC LIMIT 30")]

    def delete_feedback(self):
        with self.connect() as db:
            db.execute("DELETE FROM feedback")
