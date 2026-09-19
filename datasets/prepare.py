"""Split a local dataset file into runtime inputs and evaluator-only labels, and record a manifest.

Usage: python -m datasets.prepare DATASET SOURCE --revision REVISION [--split NAME] [--out DIR]

SOURCE must already be on disk. This command downloads nothing. Obtain each dataset from its
publisher under its license and pass the revision you obtained. Output:

  DIR/prepared/DATASET/SPLIT.visible.jsonl   what a system under test may read
  DIR/gold/DATASET/SPLIT.jsonl               labels, readable by the owner only
  DIR/prepared/DATASET/DATASET.json          hash, row count, revision, license, field names
"""
from __future__ import annotations

import argparse
from pathlib import Path

from datasets.adapters import averitec, environmental_claims, financebench, finqa, greenclaims
from datasets.adapters.base import export
from datasets.manifests.manifest import write_manifest

# The license named by each adapter's source. "unverified" means the adapter does not record one.
ADAPTERS = {
    "environmental_claims": (environmental_claims.load, "CC BY-NC-SA 4.0"),
    "averitec": (averitec.load, "CC BY-NC 4.0"),
    "finqa": (finqa.load, "MIT"),
    "financebench": (financebench.load, "CC BY-NC 4.0"),
    "greenclaims": (greenclaims.load, "unverified"),
}


def prepare(dataset: str, source: str | Path, revision: str, split: str, out: str | Path) -> Path:
    load, license = ADAPTERS[dataset]
    examples = list(load(source))
    out = Path(out)
    visible = out / "prepared" / dataset / f"{split}.visible.jsonl"
    export(examples, visible, out / "gold" / dataset / f"{split}.jsonl")
    fields = {"model_visible": sorted(examples[0].model_visible),
              "evaluation_only": sorted(examples[0].evaluation_only)} if examples else {}
    return write_manifest(dataset, source, len(examples), revision, license, [split], fields,
                          visible.parent)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", choices=sorted(ADAPTERS))
    parser.add_argument("source")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--split", default="all")
    parser.add_argument("--out", default=".")
    args = parser.parse_args()
    print(prepare(args.dataset, args.source, args.revision, args.split, args.out))


if __name__ == "__main__":
    main()
