from __future__ import annotations
import importlib.util
import json
import math
import re
from collections import Counter
from pathlib import Path
from .sources import LABELS
from .adapters import canonical_label


def keyed(rows, name):
    result = {}
    for r in rows:
        i = r.get("example_id")
        if not isinstance(i, str) or not i:
            raise ValueError(f"{name}: missing/non-string example_id")
        if i in result:
            raise ValueError(f"{name}: duplicate ID {i}")
        result[i] = r
    return result


def align(refs, predictions, selected_ids=None):
    gold, pred = keyed(refs, "references"), keyed(predictions, "predictions")
    if set(pred) - set(gold):
        raise ValueError(f"Unknown prediction IDs: {sorted(set(pred)-set(gold))[:5]}")
    ids = list(gold) if selected_ids is None else list(selected_ids)
    if not ids or len(set(ids)) != len(ids) or set(ids) - set(gold):
        raise ValueError("Selection must be nonempty, unique, and a subset of reference IDs")
    # Missing predictions remain in the denominator. Extra known IDs outside an explicitly
    # declared subset are not scored; all duplicate and unknown IDs are still errors.
    return [(gold[i], pred.get(i)) for i in ids]


def usable(row):
    return row is not None and row.get("status", "ok") == "ok" and not row.get("error")


def numeric_value(value):
    """Strict answer-only diagnostic: no extracting a convenient number from prose."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (float, int)):
        x = float(value)
        return x if math.isfinite(x) else None
    s = str(value).strip().lower().replace(",", "")
    if s in {"yes", "no"}:
        return s
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?", s):
        return None
    x = float(s.rstrip("%"))
    if s.endswith("%"):
        x /= 100
    return x if math.isfinite(x) else None


def numeric_equal(pred, gold):
    a, b = numeric_value(pred), numeric_value(gold)
    if a is None or b is None:
        return False
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return round(a, 5) == round(b, 5)


def normalize_text(value):
    return " ".join(str(value or "").casefold().split())


def load_official(path):
    if not path.exists():
        raise ValueError("Official scorer is missing. Run prepare successfully first.")
    spec = importlib.util.spec_from_file_location("upstream_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_program(program, table):
    """Allow only the published DSL; never exec/eval model output."""
    ops = {"add", "subtract", "multiply", "divide", "exp", "greater", "table_max", "table_min", "table_sum", "table_average"}
    rows = {str(r[0]) for r in table if r}
    if not isinstance(program, list) or not program or program[-1] != "EOF":
        return False
    if any(not isinstance(t, str) for t in program) or len(program) > 401 or (len(program)-1) % 4:
        return False
    if len(program) == 1:
        return False
    for n in range(0, len(program)-1, 4):
        op = program[n]
        if op not in {x + "(" for x in ops} or program[n+3] != ")":
            return False
        for pos in (1, 2):
            arg = program[n+pos]
            if len(arg) > 1000:
                return False
            if pos == 1 and op.startswith("table_") and arg in rows:
                continue
            if pos == 2 and op.startswith("table_") and arg == "none":
                continue
            if re.fullmatch(r"#\d+", arg):
                if int(arg[1:]) >= n//4:
                    return False
            elif re.fullmatch(r"const_(?:m1|[+-]?(?:\d+(?:\.\d*)?|\.\d+))", arg):
                pass
            elif numeric_value(arg) is None or numeric_value(arg) in {"yes", "no"}:
                return False
    return True


def score_finqa(pairs, *, native=None, official_path=None, answer_only=False):
    details, correct, completed, valid = [], 0, 0, 0
    evaluator = None if answer_only else load_official(official_path)
    native_map = {r["id"]: r for r in (native or [])}
    for gold, p in pairs:
        ok = usable(p)
        completed += int(ok)
        good = False
        execution = None
        failure = None
        if ok:
            if answer_only:
                execution = p.get("answer")
                valid += int(numeric_value(execution) is not None)
                good = numeric_equal(execution, gold["exe_ans"])
            else:
                raw = native_map[gold["example_id"]]
                tokens = p.get("predicted_program", p.get("predicted"))
                if safe_program(tokens, raw["table"]):
                    try:
                        invalid, execution = evaluator.eval_program(tokens, raw["table"])
                        valid += int(invalid == 0)
                        good = invalid == 0 and execution == gold["exe_ans"]
                    except Exception as exc:
                        failure = str(exc)
                else:
                    failure = "Missing or invalid published FinQA token program"
        correct += int(good)
        details.append({"example_id": gold["example_id"], "correct": good,
                        "execution": execution, "completed": ok, "error": failure})
    return {"metric": "answer_only_numeric_diagnostic_NOT_official_execution" if answer_only else "execution_accuracy_using_pinned_official_eval_program",
            "n": len(pairs), "correct": correct, "accuracy": correct/len(pairs),
            "completed": completed, "coverage": completed/len(pairs), "valid_outputs": valid,
            "program_equivalence_accuracy": None,
            "source_input_correctness": "Not automatically graded; requires source-linked review",
            "details": details}


def class_metrics(golds, predictions, labels):
    conf = {g: {p: 0 for p in labels + ["__MISSING__"]} for g in labels}
    for g, p in zip(golds, predictions):
        conf[g][p] += 1
    per = {}
    for label in labels:
        tp = sum(g == label and p == label for g, p in zip(golds, predictions))
        fp = sum(g != label and p == label for g, p in zip(golds, predictions))
        fn = sum(g == label and p != label for g, p in zip(golds, predictions))
        precision = tp/(tp+fp) if tp+fp else 0.0
        recall = tp/(tp+fn) if tp+fn else 0.0
        per[label] = {"precision": precision, "recall": recall,
                      "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0,
                      "support": sum(g == label for g in golds)}
    return {"accuracy": sum(g == p for g,p in zip(golds,predictions))/len(golds),
            "macro_f1": sum(per[l]["f1"] for l in labels)/len(labels),
            "per_class": per, "confusion": conf}


def score_averitec(pairs):
    gs, ps, briers, losses = [], [], [], []
    for gold, p in pairs:
        gs.append(gold["label"])
        pred = canonical_label(p.get("label", p.get("pred_label"))) if usable(p) else "__MISSING__"
        if pred is None:
            pred = "__MISSING__"
        if pred not in LABELS + ["__MISSING__"]:
            raise ValueError(f"Invalid prediction label {pred!r}")
        ps.append(pred)
        prob = p.get("probabilities") if usable(p) else None
        if prob is not None:
            if not isinstance(prob, dict) or set(prob) != set(LABELS):
                raise ValueError("probabilities must map every native AVeriTeC label to its probability")
            values = list(prob.values())
            if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not 0<=x<=1 for x in values):
                raise ValueError("Invalid probability")
            if not math.isclose(sum(values),1.0,abs_tol=1e-6):
                raise ValueError("Probabilities must sum to 1")
            briers.append(sum((prob[l] - (l == gold["label"]))**2 for l in LABELS))
            losses.append(-math.log(max(prob[gold["label"]],1e-15)))
    result = class_metrics(gs,ps,LABELS)
    result.update(n=len(pairs), metric="native_verdict_only_NOT_evidence_conditioned_AVeriTeC_score",
                  prediction_coverage=sum(p != "__MISSING__" for p in ps)/len(ps),
                  probability_examples=len(briers), probability_coverage=len(briers)/len(ps),
                  multiclass_brier=sum(briers)/len(briers) if briers else None,
                  log_loss_clipped_1e_15=sum(losses)/len(losses) if losses else None)
    nee_n = gs.count("Not Enough Evidence")
    result["insufficient_to_refuted_rate"] = sum(g=="Not Enough Evidence" and p=="Refuted" for g,p in zip(gs,ps))/nee_n if nee_n else None
    return result


def score_financebench(pairs, reviews=None):
    review_map = keyed(reviews or [], "reviews")
    selected = {r["example_id"] for r, _ in pairs}
    if set(review_map)-selected:
        raise ValueError("Review IDs are outside this evaluation selection")
    exact, complete, page_recalls, all_pages, review_complete = 0, 0, [], 0, 0
    correct, evidence_backed, details = 0, 0, []
    for gold, p in pairs:
        ok = usable(p) and isinstance(p.get("answer"),str) and bool(p["answer"].strip())
        complete += int(ok)
        exact += int(ok and normalize_text(p["answer"]) == normalize_text(gold["answer"]))
        expected = {(e.get("evidence_doc_name",e.get("doc_name",gold["doc_name"])), int(e["evidence_page_num"])) for e in gold["evidence"]}
        actual = set()
        if ok:
            for c in p.get("citations", []):
                page = c.get("page_index")
                if type(page) is not int or page < 0:
                    raise ValueError("Citation page_index must be a nonnegative zero-based integer")
                actual.add((c["doc_name"], page))
        recall = len(expected & actual)/len(expected) if expected else None
        if recall is not None:
            page_recalls.append(recall)
            all_pages += int(expected <= actual)
        review = review_map.get(gold["example_id"], {})
        keys = ("answer_correct", "citation_supported", "evidence_sufficient")
        reviewed = all(str(review.get(k,"")) in {"0","1"} for k in keys)
        if reviewed:
            review_complete += 1
            correct += int(ok and str(review["answer_correct"]) == "1")
            evidence_backed += int(ok and all(str(review[k]) == "1" for k in keys))
        details.append({"example_id": gold["example_id"], "completed": ok,
                        "annotated_page_recall": recall, "review_complete": reviewed})
    return {"metric": "financial_QA_diagnostics_plus_human_review",
            "n":len(pairs), "completed":complete,"coverage":complete/len(pairs),
            "normalized_exact_match_DIAGNOSTIC_ONLY":exact/len(pairs),
            "mean_annotated_citation_page_recall":sum(page_recalls)/len(page_recalls) if page_recalls else None,
            "all_annotated_pages_cited_rate":all_pages/len(page_recalls) if page_recalls else None,
            "citation_entailment_automatically_established":False,
            "human_reviewed":review_complete,"human_review_coverage":review_complete/len(pairs),
            "human_answer_accuracy_on_reviewed":correct/review_complete if review_complete else None,
            "human_evidence_backed_accuracy_on_reviewed":evidence_backed/review_complete if review_complete else None,
            "human_answer_accuracy_full_set":correct/len(pairs) if review_complete==len(pairs) else None,
            "details":details}
