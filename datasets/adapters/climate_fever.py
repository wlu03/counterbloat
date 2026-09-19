"""CLIMATE-FEVER: real-world climate claims with Wikipedia evidence. License: unverified."""
from datasets.adapters.base import Example, gold, read_rows

# Published class order. A parquet export stores the index instead of the name.
CLAIM_LABELS = ("SUPPORTS", "REFUTES", "NOT_ENOUGH_INFO", "DISPUTED")
EVIDENCE_LABELS = ("SUPPORTS", "REFUTES", "NOT_ENOUGH_INFO")


def _name(value, names):
    return names[value] if isinstance(value, int) else value


def load(path):
    for i, row in enumerate(read_rows(path)):
        evidences = row.get("evidences") or []
        yield Example(
            id=f"climate_fever-{row.get('claim_id', i)}", dataset="climate_fever",
            # The sentences are Wikipedia text; every label, vote and entropy stays with the gold.
            model_visible={"claim": row["claim"],
                           "evidence": [{"evidence_id": e["evidence_id"], "article": e["article"],
                                         "evidence": e["evidence"]} for e in evidences]},
            evaluation_only=gold("climate_fever", i,
                                 {"claim_label": _name(row.get("claim_label"), CLAIM_LABELS),
                                  "evidence_labels": [
                                      {"evidence_id": e["evidence_id"],
                                       "evidence_label": _name(e.get("evidence_label"), EVIDENCE_LABELS),
                                       "votes": e.get("votes"), "entropy": e.get("entropy")}
                                      for e in evidences]},
                                 ("claim_label",)))
