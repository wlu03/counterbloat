"""Word-category densities from the Loughran-McDonald master dictionary.

The dictionary marks each word with the year it entered a category, so any non-zero entry means
the word belongs to it. The file is free for academic use and is not redistributed with this
repository; fetch it with `python -m datasets.fetch loughran_mcdonald`.

Strong and weak modal words are short lists, nineteen and twenty-seven entries, so a hedging delta
taken over one sentence is often zero. It is a measure over a passage, not over a phrase.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from backend.claims.features import words

DICTIONARY = Path("datasets/loughran_mcdonald/source/lm_master_dictionary.csv")
CATEGORIES = ("Negative", "Positive", "Uncertainty", "Litigious",
              "Strong_Modal", "Weak_Modal", "Constraining")


class LexiconMissing(Exception):
    pass


@lru_cache(maxsize=4)
def load(path: str | Path = DICTIONARY) -> dict[str, frozenset[str]]:
    path = Path(path)
    if not path.is_file():
        raise LexiconMissing(
            f"{path} is missing. Run: python -m datasets.fetch loughran_mcdonald")
    found: dict[str, set[str]] = {name: set() for name in CATEGORIES}
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.DictReader(handle):
            word = row["Word"].strip().lower()
            if not word:
                continue
            for name in CATEGORIES:
                if (row.get(name) or "0").strip() not in ("0", ""):
                    found[name].add(word)
    return {name: frozenset(entries) for name, entries in found.items()}


def densities(text: str, path: str | Path = DICTIONARY) -> dict[str, float]:
    """Words of each category per hundred words. An empty text scores zero, not an error."""
    lexicon = load(path)
    found = [w.lower() for w in words(text)]
    if not found:
        return {name: 0.0 for name in CATEGORIES}
    return {name: 100.0 * sum(1 for w in found if w in entries) / len(found)
            for name, entries in lexicon.items()}


def hedging_delta(claim: str, passage: str, path: str | Path = DICTIONARY) -> float:
    """How much more firmly the claim is put than the filing passage it was matched to.

    Positive means the claim leans on strong modal words where the filing hedges. It measures a
    difference in wording, not whether either statement is right.
    """
    return (densities(claim, path)["Strong_Modal"]
            - densities(passage, path)["Weak_Modal"])
