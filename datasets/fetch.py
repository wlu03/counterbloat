"""Download the upstream files for a dataset the benchmark kit has no pinned downloader for.

Usage: python -m datasets.fetch DATASET [--out DIR]

Files land in DIR/DATASET/source and are not tracked. Neither publisher names a license; obtain
and use the data under the terms on their page. Each SHA256 below is the file this repository
prepared from, so a mismatch means the publisher changed it and the counts may no longer match.
"""
from __future__ import annotations

import argparse
import hashlib
import tarfile
import urllib.request
from pathlib import Path

QUANTEMP = "https://raw.githubusercontent.com/factiverse/QuanTemp/main/data"
CLIMATE_FEVER = "https://raw.githubusercontent.com/tdiggelm/climate-fever-dataset/main/dataset"
CODELOAD = "https://codeload.github.com/{repo}/tar.gz/{commit}"
MAEC_REPO = ("Earnings-Call-Dataset/"
             "MAEC-A-Multimodal-Aligned-Earnings-Conference-Call-Dataset-for-Financial-Risk-"
             "Prediction")

# Read sentence by sentence rather than split into labelled examples, so they have no adapter.
CORPORA = {"maec", "mdrm", "loughran_mcdonald"}

SOURCES = {
    "quantemp": {
        "page": "https://github.com/factiverse/QuanTemp",
        "license": "unverified",
        "files": {
            "train_claims_quantemp.json": (
                f"{QUANTEMP}/raw_data/train_claims_quantemp.json",
                "4df1543a25416d85e727f206cf4de2c509b30c7db1eb93a62e0ee3968667d626"),
            "val_claims_quantemp.json": (
                f"{QUANTEMP}/raw_data/val_claims_quantemp.json",
                "49ad37aea769714a0cf53beacd74f78d18f81b95df9d0d2bf578e2457454ccd3"),
            "test_claims_quantemp.json": (
                f"{QUANTEMP}/raw_data/test_claims_quantemp.json",
                "b0a1241b1779040db5f0862252be9122d45ff0da157c0bc5ea5ac96e9acd43a7"),
            # Retrieved evidence for each claim. The records carry the snippet text, not only IDs,
            # so the separate corpus the README links is only needed to retrieve afresh.
            "bm25_top_100_claimdecomp.json.zip": (
                f"{QUANTEMP}/bm25_scored_evidence/bm25_top_100_claimdecomp.json.zip",
                "f2312dc98d132d34853c6c8a813338a5fe899a9e59735615ae6600c2d925be35"),
            "test_claimdecomp.csv": (
                f"{QUANTEMP}/decomposed_questions/test/test_claimdecomp.csv",
                "8e9dd1a9f0e5eb47c01d30ceb8b26e02871ee18482d61c57f5c622f81cb2b9fb"),
            "fact_checkers.json": (
                f"{QUANTEMP}/fact_checkers.json",
                "bb9f0939db2596ca85b071f158b8b35f87608e5af61e5ad2a5a12ab334b8d90a"),
        },
    },
    "maec": {
        "page": f"https://github.com/{MAEC_REPO}",
        "license": "CC-BY-SA-4.0",
        "files": {
            "maec.tar.gz": (
                CODELOAD.format(repo=MAEC_REPO,
                                commit="65a109f5b1a8cb4c96e8337b749ce3db41f2c210"),
                "7de73134b5ba8d521e804ef751fd09e64b33cda09cd79549f4fb33a103c74373"),
        },
    },
    "mdrm": {
        "page": "https://github.com/GeminiLn/EarningsCall_Dataset",
        "license": "unverified",
        "files": {
            "mdrm.tar.gz": (
                CODELOAD.format(repo="GeminiLn/EarningsCall_Dataset",
                                commit="e168672f60c9adab38cd3004048e4af656e79f24"),
                "1214d122504743183f8798b6047b9242c6463c00c927faef9cdd842b84e8c9c2"),
        },
    },
    "loughran_mcdonald": {
        "page": "https://sraf.nd.edu/loughranmcdonald-master-dictionary/",
        "license": "free for academic use; commercial use needs the authors' permission",
        "files": {
            "lm_master_dictionary.csv": (
                "https://drive.google.com/uc?export=download&id="
                "1iq2RUf8qGFEAk1g8wQntP3habOnR3fXF",
                "e2d1328682bab7d2187684fb9f5420bb730401c9eefc00daf835edd203f4859d"),
        },
    },
    "climate_fever": {
        "page": "https://github.com/tdiggelm/climate-fever-dataset",
        "license": "unverified",
        "files": {
            "climate-fever.jsonl": (
                f"{CLIMATE_FEVER}/climate-fever.jsonl",
                "8a4b9032d861be482ffb49dddfd283ffa6089e654f1e968040011882c5eb6e0b"),
        },
    },
}


def fetch(dataset: str, out: str | Path = "datasets") -> Path:
    source = SOURCES[dataset]
    directory = Path(out) / dataset / "source"
    directory.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in source["files"].items():
        path = directory / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            print(f"have {path}")
            continue
        with urllib.request.urlopen(url, timeout=300) as response:
            body = response.read()
        digest = hashlib.sha256(body).hexdigest()
        if digest != expected:
            raise ValueError(f"{name} SHA256 is {digest}, not the recorded {expected}")
        path.write_bytes(body)
        print(f"wrote {path} ({len(body)/1e6:.1f} MB)")
        if name.endswith(".tar.gz"):
            with tarfile.open(path) as archive:
                archive.extractall(directory, filter="data")
            print(f"unpacked {path}")
    print(f"{dataset}: license {source['license']}; see {source['page']}")
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", choices=sorted(SOURCES))
    parser.add_argument("--out", default="datasets")
    args = parser.parse_args()
    fetch(args.dataset, args.out)


if __name__ == "__main__":
    main()
