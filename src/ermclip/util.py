from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


class Cancelled(Exception):
    pass


class UnsupportedRequest(ValueError):
    pass


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path: Path, data):
    atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def slug(value: str):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")[:70] or "video"


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def validate_input(path: str | Path, allowed: list[str]) -> Path:
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_file() or resolved.suffix.lower() not in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"):
        raise ValueError("Input must be a supported local video file")
    if not any(resolved.is_relative_to(Path(folder).expanduser().resolve()) for folder in allowed):
        raise ValueError("Source is outside configured allowed_inputs")
    return resolved


def run(args: list[str], *, timeout=7200, cwd=None, check_cancel=None) -> subprocess.CompletedProcess:
    # File-backed output prevents pipe deadlocks on long FFmpeg diagnostics.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen([str(a) for a in args], cwd=cwd, stdout=stdout, stderr=stderr,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        started = time.monotonic()
        try:
            while process.poll() is None:
                if check_cancel and check_cancel():
                    raise Cancelled("Job cancelled")
                if time.monotonic() - started > timeout:
                    raise TimeoutError(f"{Path(args[0]).name} exceeded {timeout} seconds")
                time.sleep(0.1)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        stdout.seek(0)
        stderr.seek(0)
        result = subprocess.CompletedProcess(args, process.returncode, stdout.read().decode("utf-8", "replace"), stderr.read().decode("utf-8", "replace"))
        if result.returncode:
            raise RuntimeError(f"{Path(args[0]).name} failed ({result.returncode}): {result.stderr[-5000:]}")
        return result
