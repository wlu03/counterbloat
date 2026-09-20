"""Run the dataset experiments on Modal: one container per shard, so the waiting on the model
provider happens in parallel rather than one example after another.

    modal run modal_app/experiments.py --dataset quantemp --system A2 --limit 40 --seed 5
    modal run modal_app/experiments.py --dataset climate_fever --system A1 --limit 100 --shards 10

Predictions come back to the same path a local run writes, results/<dataset>_<system>.jsonl, and
are scored locally afterwards with:

    uv run python -m evaluation.experiments.run score --dataset DATASET \\
        --predictions results/DATASET_SYSTEM.jsonl --gold gold/DATASET/SPLIT.jsonl --out R.json

The gold labels are never uploaded. A container is given the claims and the documents it may
search, and nothing else, so a system under test cannot read the answer here either.

Needs a Modal secret named "counterbloat" holding OPENAI_API_KEY, OPENAI_EXTRACT_MODEL,
OPENAI_REASON_MODEL, and OPENAI_REASONING_EFFORT. Create it from the local .env without printing
any key:

    modal secret create counterbloat --from-dotenv .env
"""
from __future__ import annotations

import json
from pathlib import Path

import modal

REPO_ROOT = Path(__file__).resolve().parent.parent
REMOTE = "/root/repo"
RESULTS_VOL = "counterbloat-results"
SPLITS = {"quantemp": "test", "climate_fever": "all", "averitec": "all"}


def _code(path) -> bool:
    """Code and prepared inputs only: caches, results, and local databases are left out."""
    parts = Path(path).parts
    return bool({"__pycache__", ".pytest_cache", "objects", "results"} & set(parts)) or \
        Path(path).suffix in (".pyc", ".db", ".log")


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("pydantic==2.13.5", "sqlalchemy==2.0.54", "httpx==0.28.1", "lxml==6.1.3",
                 "openai==3.16.2", "pyyaml>=6")
    .env({"PYTHONPATH": REMOTE, "OBJECT_STORE_DIR": "/tmp/objects"})
    .add_local_dir(REPO_ROOT / "backend", f"{REMOTE}/backend", ignore=_code)
    .add_local_dir(REPO_ROOT / "evaluation", f"{REMOTE}/evaluation", ignore=_code)
    .add_local_dir(REPO_ROOT / "config", f"{REMOTE}/config", ignore=_code)
    # Only the adapters, because datasets/ also holds the upstream sources, which are large and
    # which nothing here reads.
    .add_local_dir(REPO_ROOT / "datasets/adapters", f"{REMOTE}/datasets/adapters", ignore=_code)
    .add_local_file(REPO_ROOT / "datasets/__init__.py", f"{REMOTE}/datasets/__init__.py")
    # The claims and the documents a system may search. The gold labels stay on this machine.
    .add_local_dir(REPO_ROOT / "prepared", f"{REMOTE}/prepared", ignore=_code)
)

app = modal.App("counterbloat-experiments", image=image)
results_vol = modal.Volume.from_name(RESULTS_VOL, create_if_missing=True)


def _rows(dataset: str, name: str) -> list[dict]:
    path = Path(REMOTE) / "prepared" / dataset / f"{SPLITS[dataset]}.{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@app.function(cpu=1, memory=2048, timeout=4 * 3600, volumes={"/results": results_vol},
              secrets=[modal.Secret.from_name("counterbloat")], max_containers=24)
def run_shard(dataset: str, system: str, ids: list[str], updater: str | None, max_calls: int,
              tag: str) -> str:
    """Run one shard of examples and return their predictions as JSON lines.

    Text rather than objects, because a prediction holds the backend's own enum types and this
    machine is not meant to need the backend installed to read a result.
    """
    import os
    import sys

    sys.path.insert(0, REMOTE)
    # The secret carries the whole local .env, including paths and addresses of services that do
    # not exist in a container. Only the provider settings apply here.
    os.environ["OBJECT_STORE_DIR"] = "/tmp/objects"
    for name in ("DATABASE_URL", "ELASTICSEARCH_URL", "ELASTIC_ENDPOINT", "COUNTERCHECK_API_URL"):
        os.environ.pop(name, None)
    from backend.config import load_settings
    from backend.providers.openai_client import OpenAILLM
    from evaluation.experiments.run import run_rows, verify
    from evaluation.experiments.tasks import VERIFICATION

    wanted = set(ids)
    rows = [r for r in _rows(dataset, "visible") if r["id"] in wanted]
    sources: dict[str, list[dict]] = {}
    for document in _rows(dataset, "searchable"):
        if document["example_id"] in wanted:
            sources.setdefault(document["example_id"], []).append(document)
    settings = load_settings(f"{REMOTE}/config/evaluation.yaml")
    if updater:
        settings.assessment.updater = updater
    task = VERIFICATION[dataset]

    def one(row, factory):
        return verify(row, factory, sources, task, system, settings)

    lines = "\n".join(json.dumps(p, default=str) for p in run_rows(rows, one, OpenAILLM, max_calls))
    # Written to the volume as well, so a long run survives losing the local connection.
    shard = Path("/results") / tag
    shard.mkdir(parents=True, exist_ok=True)
    (shard / f"{ids[0]}.jsonl").write_text(lines)
    results_vol.commit()
    return lines


@app.local_entrypoint()
def main(dataset: str, system: str = "A2", limit: int = 40, seed: int = 5, shards: int = 8,
         updater: str = "", max_calls: int = 400, out: str = ""):
    import random

    if dataset not in SPLITS:
        raise SystemExit(f"dataset must be one of {', '.join(SPLITS)}")
    visible = REPO_ROOT / "prepared" / dataset / f"{SPLITS[dataset]}.visible.jsonl"
    if not visible.exists():
        raise SystemExit(f"{visible} is missing; prepare the dataset first")
    rows = [json.loads(line) for line in visible.read_text().splitlines() if line.strip()]
    sample = random.Random(seed).sample(rows, limit) if limit < len(rows) else rows
    ids = [r["id"] for r in sample]
    groups = [ids[i::shards] for i in range(min(shards, len(ids)))]
    tag = f"{dataset}_{system}_{seed}"
    print(f"{len(ids)} examples over {len(groups)} containers, seed {seed}, "
          f"at most {max_calls} provider calls per container")

    predictions: list[dict] = []
    for lines in run_shard.starmap([(dataset, system, g, updater or None, max_calls, tag)
                                    for g in groups]):
        predictions += [json.loads(line) for line in lines.splitlines() if line.strip()]
    order = {example: i for i, example in enumerate(ids)}
    predictions.sort(key=lambda p: order.get(str(p["id"]), len(order)))
    destination = Path(out) if out else REPO_ROOT / "results" / f"{dataset}_{system}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(json.dumps(p, default=str) for p in predictions) + "\n")
    ran = sum(p["status"] != "not_run" for p in predictions)
    print(f"{destination}: {len(predictions)} predictions, {ran} ran")
