"""FinQA: numerical reasoning over financial text and tables. Repository license: MIT."""
from datasets.adapters.base import Example, gold, read_rows


def load(path):
    for i, row in enumerate(read_rows(path)):
        qa = row["qa"]
        yield Example(
            id=row.get("id", f"finqa-{i}"), dataset="finqa",
            model_visible={"question": qa["question"], "pre_text": row["pre_text"],
                           "post_text": row["post_text"], "table": row["table"]},
            evaluation_only=gold("finqa", i, {"program": qa.get("program"),
                                              "exe_ans": qa.get("exe_ans"),
                                              "answer": qa.get("answer"),
                                              "gold_inds": qa.get("gold_inds")},
                                 ("program", "exe_ans")))
