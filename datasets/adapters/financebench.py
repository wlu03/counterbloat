"""FinanceBench public sample of 150 examples. CC BY-NC 4.0. Kept as a local holdout."""
from datasets.adapters.base import Example, gold, read_rows


def load(path):
    for i, row in enumerate(read_rows(path)):
        yield Example(
            id=row.get("financebench_id", f"financebench-{i}"), dataset="financebench",
            model_visible={"question": row["question"], "doc_name": row.get("doc_name"),
                           "doc_link": row.get("doc_link")},
            evaluation_only=gold("financebench", i, {"answer": row.get("answer"),
                                                     "justification": row.get("justification"),
                                                     "evidence": row.get("evidence")},
                                 ("answer", "evidence")))
