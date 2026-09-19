from __future__ import annotations
import hashlib
import json
import os
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from typing import Iterable, Any


def digest(path: Path, algorithm="sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_blob_hash(path: Path) -> str:
    h = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_jsonl(path: Path, rows: Iterable[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    os.replace(tmp, path)


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        start = f.read(1)
        f.seek(0)
        if path.suffix == ".jsonl":
            rows = [json.loads(line) for line in f if line.strip()]
        else:
            rows = json.load(f)
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError(f"Expected a list of records: {path}")
    return rows


def download(url: str, dest: Path, *, sha256: str | None = None,
             blob_sha1: str | None = None, attempts: int = 3) -> dict:
    """Stream/resume a pinned public URL; no third-party keys or external paid services."""
    def verify():
        if sha256 and digest(dest) != sha256:
            raise ValueError(f"SHA256 mismatch: {dest}")
        if blob_sha1 and git_blob_hash(dest) != blob_sha1:
            raise ValueError(f"Git blob SHA1 mismatch: {dest}")
    if dest.exists():
        verify()
        return {"url": url, "path": str(dest), "bytes": dest.stat().st_size,
                "sha256": digest(dest), "cache_hit": True}
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(attempts):
        try:
            offset = part.stat().st_size if part.exists() else 0
            headers = {"User-Agent": "Counterbloat-public-benchmark-kit/1.0", "Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=120) as response:
                resumed = offset and response.status == 206
                if resumed and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("Server resumed at an unexpected byte offset")
                expected_length = response.headers.get("Content-Length")
                received = 0
                with part.open("ab" if resumed else "wb") as f:
                    for block in iter(lambda: response.read(1024 * 1024), b""):
                        f.write(block)
                        received += len(block)
                if expected_length and received != int(expected_length):
                    raise OSError(f"Incomplete HTTP body: got {received}, expected {expected_length}")
            os.replace(part, dest)
            try:
                verify()
            except ValueError:
                dest.unlink(missing_ok=True)
                raise
            return {"url": url, "path": str(dest), "bytes": dest.stat().st_size,
                    "sha256": digest(dest), "cache_hit": False}
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 416:
                part.unlink(missing_ok=True)
            if exc.code in {401, 403, 404}:
                break
        except (OSError, ValueError) as exc:
            last = exc
        if attempt + 1 < attempts:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Download failed: {url}\n{last}\nNo success manifest was produced.")


def extract_json_archive(archive: Path, destination: Path, max_bytes: int = 120 * 1024**3):
    """Only JSON/JSONL members; no pickle loading, unsafe paths, or symlinks."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as z:
        eligible = [i for i in z.infolist() if not i.is_dir()
                    and Path(i.filename).suffix.lower() in {".json", ".jsonl"}]
        if sum(i.file_size for i in eligible) > max_bytes:
            raise ValueError("Archive exceeds configured uncompressed byte limit")
        seen = set()
        for info in eligible:
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root) or "\\" in info.filename:
                raise ValueError(f"Unsafe archive member: {info.filename}")
            if target in seen:
                raise ValueError(f"Duplicate archive member: {info.filename}")
            seen.add(target)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError("Symlink in archive")
        for info in eligible:
            target = root / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as dst:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(block)
    if not eligible:
        raise ValueError("Archive contains no JSON/JSONL files; no corpus was imported")
    return len(eligible)
