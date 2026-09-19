from __future__ import annotations
import copy
import html
from pathlib import Path
from .sources import LABELS
from .io import write_json, write_jsonl


def canonical_label(value):
    if value == "Conflicting Evidence/Cherry-picking":
        return "Conflicting Evidence/Cherrypicking"
    return value


def convert(dataset: str, rows: list[dict]):
    """Allowlist inputs; return (inputs, evaluator references, native reference rows)."""
    inputs, refs = [], []
    for index, row in enumerate(rows):
        if dataset == "finqa":
            qa = row["qa"]
            example_id = row["id"]
            inp = {"example_id": example_id, "dataset": dataset, "task": "financial_numeric_qa",
                   "question": qa["question"], "pre_text": row["pre_text"],
                   "post_text": row["post_text"], "table": row["table"]}
            ref = {"example_id": example_id, "answer": qa.get("answer"),
                   "exe_ans": qa["exe_ans"], "program": qa["program"],
                   "gold_inds": qa.get("gold_inds", {})}
        elif dataset == "financebench":
            example_id = str(row["financebench_id"])
            inp = {"example_id": example_id, "dataset": dataset, "task": "financial_report_qa",
                   "question": row["question"], "company": row["company"], "doc_name": row["doc_name"]}
            ref = {"example_id": example_id, "answer": row["answer"],
                   "evidence": row["evidence"], "justification": row.get("justification"),
                   "question_type": row.get("question_type"), "company": row["company"],
                   "doc_name": row["doc_name"]}
        elif dataset == "averitec":
            # Official FEVER-7 knowledge-store files use the original zero-based row order.
            example_id = f"averitec-dev-{index:04d}"
            label = canonical_label(row["label"])
            if label not in LABELS:
                raise ValueError(f"Unexpected AVeriTeC label: {label!r}")
            inp = {"example_id": example_id, "dataset": dataset, "task": "claim_verification",
                   "claim_id": index, "claim": row["claim"]}
            for field in ("claim_date", "speaker", "original_claim_url", "cached_original_claim_url",
                          "reporting_source", "location_ISO_code"):
                inp[field] = row.get(field)
            ref = {"example_id": example_id, "claim_id": index, "label": label,
                   "questions": row["questions"], "justification": row.get("justification"),
                   "fact_checking_article": row.get("fact_checking_article")}
        else:
            raise ValueError(f"Unknown dataset: {dataset}")
        if not isinstance(example_id, str) or not example_id:
            raise ValueError("Empty/non-string example ID")
        inputs.append(copy.deepcopy(inp))
        refs.append(copy.deepcopy(ref))
    ids = [r["example_id"] for r in inputs]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate example IDs in source dataset")
    return inputs, refs, copy.deepcopy(rows)


def finqa_context(row):
    """Identical table formatting for every row, independent of reference annotations."""
    table = row["table"]
    chunks = [{"chunk_id": f"text_{i}", "kind": "text", "text": value}
              for i, value in enumerate(row["pre_text"] + row["post_text"])]
    for i, cells in enumerate(table):
        chunks.append({"chunk_id": f"table_{i}", "kind": "table_row", "row_index": i,
                       "text": " | ".join(str(x) for x in cells),
                       "cells": cells, "column_headers": table[0] if table else []})
    return chunks


def write_prepared(root: Path, dataset: str, rows: list[dict], expected_count: int | None):
    if expected_count is not None and len(rows) != expected_count:
        raise ValueError(f"Expected {expected_count} {dataset} examples, found {len(rows)}. Refusing silent split drift.")
    inputs, refs, native = convert(dataset, rows)
    write_jsonl(root / "runtime/inputs.jsonl", inputs)
    write_jsonl(root / "evaluator_only/references.jsonl", refs)
    write_json(root / "evaluator_only/native_references.json", native)
    if dataset == "finqa":
        write_jsonl(root / "runtime/corpus/excerpts.jsonl",
                    ({"example_id": r["example_id"], "chunks": finqa_context(r)} for r in inputs))
    write_json(root / "runtime/metadata.json", {
        "dataset": dataset, "count": len(inputs),
        "evidence_setting": "complete_supplied_excerpt" if dataset == "finqa" else "corpus_not_yet_prepared",
        "references_in_runtime": False,
        "warning": "Folder separation is not a security sandbox. Mount only runtime/ in the inference worker."})
    return inputs, refs


def oracle_inputs(dataset, inputs, refs):
    ref_by_id = {r["example_id"]: r for r in refs}
    output = []
    for inp in inputs:
        r = ref_by_id[inp["example_id"]]
        item = copy.deepcopy(inp)
        item["evidence_setting"] = "ORACLE_ANNOTATED_EVIDENCE_NOT_RETRIEVAL"
        if dataset == "financebench":
            item["oracle_evidence"] = [{"text": e["evidence_text"],
                "doc_name": e.get("evidence_doc_name", e.get("doc_name", r["doc_name"])),
                "page_index": e["evidence_page_num"]} for e in r["evidence"]]
        elif dataset == "averitec":
            item["oracle_evidence"] = r["questions"]
        else:
            raise ValueError("FinQA normal mode already supplies the full released excerpt; use its normal inputs.")
        output.append(item)
    return output
