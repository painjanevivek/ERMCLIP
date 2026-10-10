"""Project-owned CUDA server. No proxy, download, credentials or cloud fallback."""
import json
import os
from pathlib import Path
import subprocess
import secrets
import time
from urllib.request import Request, build_opener, ProxyHandler

import psutil
from .provider import NoRedirect

ALIAS = "ermclip-qwen3-4b"
URL = "http://127.0.0.1:8088"


def ready(settings):
    try:
        key=(settings.path / "state" / "local-model.key").read_text(encoding="utf-8").strip()
        request=Request(URL + "/v1/models", headers={"Authorization":"Bearer " + key})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=2) as response:
            body = json.loads(response.read(65536))
        return any(m.get("id") == settings.director_model for m in body.get("data", []))
    except (OSError, ValueError):
        return False


def ensure(settings):
    if not settings.managed_local_model:
        return
    # Keep concurrent operator calls from starting a second GPU server.
    from .worker import worker_lock
    with worker_lock(settings.path / "state" / "model-start.lock"):
        if ready(settings):
            return
        manifest_path = settings.path / "cache" / "local-llm" / "install.json"
        if not manifest_path.exists():
            raise RuntimeError("Run scripts/install_local_model.py first")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get('alias') != settings.director_model:
            raise RuntimeError('Installed model alias does not match the local configuration')
        assets = (settings.path / "cache" / "local-llm").resolve()
        server, model = Path(manifest["server"]).resolve(), Path(manifest["model"]).resolve()
        if not all(p.is_relative_to(assets) and p.is_file() for p in (server, model)):
            raise RuntimeError("Runtime files must exist inside the project model cache")
        key_path=settings.path / "state" / "local-model.key"
        if not key_path.exists():
            key_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        args = [str(server), "--model", str(model), "--alias", settings.director_model,
                "--host", "127.0.0.1", "--port", "8088", "--offline",
                "--api-key-file", str(key_path), "--device", "CUDA0",
                "--ctx-size", str(settings.local_context_tokens) if settings.director_model=='ermclip-qwen35-9b' else "16384", "--parallel", "1", "--n-gpu-layers", "99", "--jinja",
                "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
                "--threads", "8", "--batch-size", "512", "--ubatch-size", "256",
                "--no-webui", "--no-slots", "--no-warmup"]
        log = settings.path / "logs" / "local-model.log"
        with log.open("ab") as stream:
            process = subprocess.Popen(args, cwd=server.parent, stdout=stream, stderr=stream,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        record = {"pid": process.pid, "created": psutil.Process(process.pid).create_time(), "server": str(server), "model": str(model), "url": URL, "args": args}
        (settings.path / "state" / "local-model.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Local model exited. Inspect {log}")
            if ready(settings):
                return
            time.sleep(0.5)
        process.terminate()
        process.wait(timeout=10)
        raise RuntimeError(f"Local model did not become ready. Inspect {log}")


def stop(settings):
    record_path = settings.path / "state" / "local-model.json"
    if not record_path.exists():
        return
    record = json.loads(record_path.read_text(encoding="utf-8"))
    try:
        process = psutil.Process(record["pid"])
        if abs(process.create_time() - record["created"]) > 0.01 or Path(process.exe()).resolve() != Path(record["server"]).resolve():
            raise RuntimeError("Server process identity changed; refusing to stop an unrelated process")
        process.terminate()
        process.wait(timeout=10)
    except psutil.NoSuchProcess:
        pass


if __name__ == "__main__":
    import sys
    from .config import load
    settings = load()
    stop(settings) if "--stop" in sys.argv else ensure(settings)
    print("Local model stopped." if "--stop" in sys.argv else f"Local model ready: {URL}; {settings.director_model}" if settings.managed_local_model else "Managed local model is disabled.")
