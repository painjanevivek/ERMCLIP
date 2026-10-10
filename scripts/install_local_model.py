"""Install pinned public model/runtime files. Inference never uses this downloader."""
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import zipfile
import argparse

ROOT = Path(__file__).resolve().parents[1]
BUILD = "b11429"
REVISION = "a06e946bb6b655725eafa393f4a9745d460374c9"
MODEL = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
FILES = [
    (f"https://github.com/ggml-org/llama.cpp/releases/download/{BUILD}/llama-{BUILD}-bin-win-cuda-12.4-x64.zip", "llama-cuda.zip", "dd6df685c1024e6aa55ca55ad35038692d5e284d4dc895e7a646c3245d3d14ff"),
    (f"https://github.com/ggml-org/llama.cpp/releases/download/{BUILD}/cudart-llama-bin-win-cuda-12.4-x64.zip", "llama-cudart.zip", "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"),
    (f"https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/{REVISION}/{MODEL}", MODEL, "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"),
]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['4b', '9b'], default='4b')
    args = parser.parse_args()
    revision, model_name, alias = REVISION, MODEL, 'ermclip-qwen3-4b'
    files = list(FILES)
    if args.model == '9b':
        revision = '3885219b6810b007914f3a7950a8d1b469d598a5'
        model_name = 'Qwen3.5-9B-Q4_K_M.gguf'
        alias = 'ermclip-qwen35-9b'
        files[-1] = (f'https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/{revision}/{model_name}', model_name, '03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8')
    assets = ROOT / "cache" / "local-llm"
    runtime = assets / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    records = []
    for url, name, digest in files:
        target = assets / name
        if not target.exists() or sha256(target) != digest:
            partial = target.with_suffix(target.suffix + ".part")
            request = urllib.request.Request(url, headers={"User-Agent": "ERMCLIP-local-setup"})
            with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as stream:
                size = int(response.headers.get("Content-Length", 0))
                total, last = 0, time.monotonic()
                while chunk := response.read(8 * 1024 * 1024):
                    stream.write(chunk)
                    total += len(chunk)
                    if time.monotonic() - last > 10:
                        print(f"{name}: {total / 1e6:.0f} / {size / 1e6:.0f} MB", flush=True)
                        last = time.monotonic()
            if sha256(partial) != digest:
                raise RuntimeError(f"SHA256 check failed for {name}")
            partial.replace(target)
        print(f"Verified {name}", flush=True)
        # Do not overwrite DLLs held by an already running verified server.
        if name.endswith(".zip"):
            with zipfile.ZipFile(target) as archive:
                for member in archive.infolist():
                    resolved = (runtime / member.filename).resolve()
                    if not resolved.is_relative_to(runtime.resolve()):
                        raise RuntimeError("Unsafe archive path")
                for member in archive.infolist():
                    destination=runtime / member.filename
                    if not destination.exists() or (not member.is_dir() and destination.stat().st_size != member.file_size):
                        archive.extract(member, runtime)
        records.append({"url": url, "path": str(target), "sha256": digest, "bytes": target.stat().st_size})
    servers = list(runtime.rglob("llama-server.exe"))
    if len(servers) != 1:
        raise RuntimeError("Expected one llama-server.exe")
    manifest = {"build": BUILD, "model_revision": revision, "server": str(servers[0]), "model": str(assets / model_name), "alias": alias, "files": records, "paid_cost": 0}
    (assets / ('install-' + args.model + '.json')).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (assets / "install.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Local model and CUDA runtime installed. No inference API was used.")


if __name__ == "__main__":
    main()
