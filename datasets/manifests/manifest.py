"""Record what was imported: file hash, row count, revision, license, and field mapping."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def write_manifest(dataset_id: str, source: str | Path, rows: int, revision: str, license: str,
                   split_names: list[str], field_mapping: dict,
                   out_dir: str | Path = "datasets/manifests") -> Path:
    record = {
        "dataset": dataset_id, "revision": revision, "license": license,
        "downloaded_at": datetime.now(UTC).isoformat(), "rows": rows, "split_names": split_names,
        "sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        "field_mapping": field_mapping,
    }
    path = Path(out_dir) / f"{dataset_id}.json"
    path.write_text(json.dumps(record, indent=2))
    return path
