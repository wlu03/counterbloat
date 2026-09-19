"""ASA adapter for the uploaded v0.1.0 starter pack, not an official ASA benchmark.

Only retrospective draft comparison is currently ready. The independent packet
contains no admitted evidence; never infer independent-detection performance.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .io import digest, read_rows, write_json, write_jsonl
from .scoring import keyed, usable, class_metrics

SOURCE_SHA256 = "95119566d269a3194bff913fda98cb65f9a461a9e53dcf99ee0d0b871d8f3157"
SOURCE_PREFIX = "ASA_test_pack_2026-09-19/"
MATERIAL_MAP = {"Present": "present", "Absent": "absent", "Undetermined": "undetermined"}
EVIDENCE_MAP = {"Supported": "supported", "Contradicted": "contradicted", "Mixed": "mixed",
                "Insufficient": "insufficient", "Not yet resolvable": "not_yet_resolvable"}
MATERIAL = list(MATERIAL_MAP.values())
EVIDENCE = list(EVIDENCE_MAP.values())
MODES = ("retrospective", "independent")
EXPECTED_COUNT = 30

INPUT_KEYS = {
    "example_id", "dataset", "task", "claim_id", "claim", "company", "brand", "product",
    "ad_variant", "claim_representation", "context_paraphrase", "original_claim_is_excerpt",
    "full_original_ad_available", "observed_date", "observed_date_precision", "first_publication_date",
    "mode", "assessment_cutoff", "evidence_setting", "allowed_evidence_ids",
}
COMMON_FIELDS = (
    "company", "brand", "product", "ad_variant", "claim_representation", "context_paraphrase",
    "original_claim_is_excerpt", "full_original_ad_available", "observed_date",
    "observed_date_precision", "first_publication_date",
)
DOC_KEYS = {"example_id", "document_id", "source_document_id", "kind", "source_url", "source_date",
            "locator", "text", "answer_bearing", "full_ruling_reproduced", "text_sha256"}


def require_mode(mode):
    if mode not in MODES:
        raise ValueError("ASA requires --mode retrospective or --mode independent")


def canonical(value, mapping, name):
    if not isinstance(value, str):
        raise ValueError(f"ASA {name} must be a string")
    if value in mapping:
        return mapping[value]
    if value in mapping.values():
        return value
    raise ValueError(f"Unknown ASA {name}: {value!r}")


def _index(rows, key):
    result = {}
    for row in rows:
        ident = row.get(key)
        if not isinstance(ident, str) or not ident or ident in result:
            raise ValueError(f"Missing, invalid, or duplicate ASA {key}: {ident!r}")
        result[ident] = row
    return result


def load_source(archive: Path):
    """Read JSON from the pinned archive; never extract/execute its scripts."""
    if digest(archive) != SOURCE_SHA256:
        raise ValueError("ASA source archive SHA256 does not match the uploaded pinned pack")
    with zipfile.ZipFile(archive) as z:
        names = set()
        if sum(i.file_size for i in z.infolist()) > 20 * 1024**2:
            raise ValueError("ASA archive exceeds the small-source size limit")
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename or info.filename in names:
                raise ValueError("Unsafe or duplicate ASA archive member")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("ASA archive contains a symlink")
            names.add(info.filename)
        checksums = json.loads(z.read(SOURCE_PREFIX + "SHA256SUMS.json"))
        for name, expected in checksums.items():
            value = z.read(SOURCE_PREFIX + name)
            if hashlib.sha256(value).hexdigest() != expected:
                raise ValueError(f"ASA upstream member checksum failed: {name}")
        def rows(name):
            return [json.loads(s) for s in z.read(SOURCE_PREFIX+name).decode('utf-8-sig').splitlines() if s.strip()]
        return {
            "claim_inputs": rows("data/claim_inputs.jsonl"),
            "retrospective_inputs": rows("data/retrospective_inputs.jsonl"),
            "references": rows("evaluator/reference_drafts.jsonl"),
            "manifest": json.loads(z.read(SOURCE_PREFIX+"manifest.json")),
            "readme": z.read(SOURCE_PREFIX+"README.md"),
        }


def convert(source, mode):
    require_mode(mode)
    claims = _index(source["claim_inputs"], "claim_id")
    retros = _index(source["retrospective_inputs"], "claim_id")
    gold = _index(source["references"], "claim_id")
    if not (set(claims) == set(retros) == set(gold)):
        raise ValueError("ASA source files have different claim ID sets")
    inputs, refs, documents, mappings = [], [], [], []
    for claim_id, claim in claims.items():
        retro, native = retros[claim_id], gold[claim_id]
        # Mode-independent content must not be reconstructed using the verdict.
        for field in ("original_claim_excerpt", *COMMON_FIELDS):
            if claim.get(field) != retro.get(field):
                raise ValueError(f"{claim_id}: claim content differs between modes: {field}")
        evidence = (retro.get("allowed_evidence_documents", []) if mode == "retrospective"
                    else claim.get("allowed_independent_evidence_documents", []))
        ids = []
        for doc in evidence:
            local_id = doc["document_id"]
            # One ruling's '-summary' ID may contain different issue summaries.
            # Namespace by assertion, not just ruling; preserve the native ID for exports.
            document_id = f"{claim_id}:{local_id}"
            text = doc["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"{document_id}: empty evidence text")
            documents.append({
                "example_id": claim_id, "document_id": document_id, "source_document_id": local_id,
                "kind": doc["type"], "source_url": doc.get("source_url"),
                "source_date": doc.get("source_date"), "locator": doc.get("locator"), "text": text,
                "answer_bearing": doc.get("answer_bearing") is True,
                "full_ruling_reproduced": doc.get("full_ruling_reproduced") is True,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            })
            ids.append(document_id)
        row = {"example_id": claim_id, "claim_id": claim_id, "dataset": "asa",
               "task": "corporate_claim_assessment", "claim": claim["original_claim_excerpt"],
               **{k: copy.deepcopy(claim.get(k)) for k in COMMON_FIELDS}, "mode": mode,
               "assessment_cutoff": retro.get("assessment_cutoff") if mode == "retrospective"
                                    else claim.get("independent_assessment_cutoff"),
               "evidence_setting": ("RETROSPECTIVE_ANSWER_BEARING_SUMMARY" if mode == "retrospective"
                                    else "CLAIM_ONLY_NOT_READY_FOR_INDEPENDENT_EVALUATION"),
               "allowed_evidence_ids": ids}
        reference = copy.deepcopy(native)
        reference.update(example_id=claim_id, dataset="asa", reference_mode=mode,
            draft_material_overstatement=canonical(native["draft_material_overstatement"], MATERIAL_MAP, "material label"),
            draft_evidence_status=canonical(native["draft_evidence_status"], EVIDENCE_MAP, "evidence status"),
            allowed_evidence_ids=ids)
        reviewed = reference.get("reviewed_reference_assessment")
        if isinstance(reviewed, dict):
            reviewed["material_overstatement"] = canonical(reviewed["material_overstatement"], MATERIAL_MAP, "material label")
            reviewed["evidence_status"] = canonical(reviewed["evidence_status"], EVIDENCE_MAP, "evidence status")
        inputs.append(row); refs.append(reference)
        mappings.append({"example_id": claim_id, "native_claim_id": claim_id,
                         "company_group": native["company_group"], "campaign_group": native["campaign_group"],
                         "ruling_id": native["ruling_id"]})
    _index(documents, "document_id")
    return inputs, refs, documents, mappings


def prepare(root, archive, mode, accept_license):
    require_mode(mode)
    if not accept_license:
        raise ValueError("Read THIRD_PARTY_NOTICES.md and pass --accept-license; no new redistribution license is granted")
    if (root/"manifest.json").exists():
        old = json.loads((root/"manifest.json").read_text())
        if old.get("mode") != mode or old.get("dataset") != "asa":
            raise ValueError("Refusing to mix ASA modes or datasets in one data directory")
    source = load_source(archive)
    inputs, refs, docs, mappings = convert(source, mode)
    if len(inputs) != EXPECTED_COUNT:
        raise ValueError("Unexpected ASA source count")
    # Do not overwrite curated files silently; an unchanged preparation is idempotent.
    if (root/"manifest.json").exists():
        validate(root, mode)
        print(f"ASA {mode} already prepared and unchanged; no files overwritten.")
        return
    if (root/"runtime").exists() or (root/"evaluator_only").exists():
        raise ValueError("Incomplete ASA directory exists; use a new empty --data-dir")
    write_jsonl(root/"runtime/inputs.jsonl", inputs)
    write_jsonl(root/"runtime/corpus/passages.jsonl", docs)
    write_jsonl(root/"evaluator_only/references.jsonl", refs)
    write_json(root/"evaluator_only/native_references.json", source["references"])
    write_jsonl(root/"evaluator_only/id_mapping.jsonl", mappings)
    write_json(root/"evaluator_only/upstream_manifest.json", source["manifest"])
    (root/"evaluator_only/UPSTREAM_README.md").write_bytes(source["readme"])
    metadata = {
        "dataset": "asa", "mode": mode, "count": len(inputs), "task": "corporate_claim_assessment",
        "evidence_setting": inputs[0]["evidence_setting"], "evidence_documents": len(docs),
        "answer_bearing_evidence": mode == "retrospective", "explicit_reference_labels_in_runtime": False,
        "independent_scoring_ready": False, "reference_status": "unreviewed_compiler_drafts",
        "source_reconstruction": "Short excerpts and context paraphrases, not full original advertisements",
        "warning": ("Retrospective inputs deliberately include answer-bearing summaries; not independent detection."
                    if mode == "retrospective" else "Claim-ingestion candidates only: no independent evidence or adjudication."),
        "isolation_note": "Mount only this mode's runtime directory; Python adapters are not sandboxed.",
    }
    write_json(root/"runtime/metadata.json", metadata)
    checksums = {str(p.relative_to(root)): digest(p) for top in ("runtime", "evaluator_only")
                 for p in sorted((root/top).rglob('*')) if p.is_file()}
    manifest = {"kit_version": "1.1.0", "dataset": "asa", "mode": mode,
        "prepared_at": datetime.now(timezone.utc).isoformat(), "count": len(inputs),
        "source_archive_sha256": SOURCE_SHA256, "source_version": source["manifest"]["version"],
        "source_assertion_count": len(inputs), "source_ruling_count": len({r['ruling_id'] for r in refs}),
        "source_company_group_count": len({r['company_group'] for r in refs}),
        "draft_material_counts": dict(Counter(r['draft_material_overstatement'] for r in refs)),
        "draft_evidence_status_counts": dict(Counter(r['draft_evidence_status'] for r in refs)),
        "source_dataset_bytes_bundled": True, "independent_ready_count": 0,
        "adjudicated_reference_count": 0, "corpus_status": metadata['evidence_setting'],
        "inference_was_run": False, "prepared_file_sha256": checksums,
        "split": "diagnostic_no_train_dev_test_split", "label_mapping": {"material": MATERIAL_MAP, "evidence": EVIDENCE_MAP}}
    write_json(root/"manifest.json", manifest)
    validate(root, mode)
    print(f"Prepared {len(inputs)} ASA {mode} records; {len(docs)} supplied evidence summaries. No model inference run.")


def assert_runtime_mode(root, mode, *, require_ready=False):
    """Runtime-only gate: never loads labels during inference."""
    require_mode(mode)
    meta = json.loads((root/"runtime/metadata.json").read_text())
    if meta.get("dataset") != "asa" or meta.get("mode") != mode:
        raise ValueError("ASA packet mode differs from --mode; use separate data directories")
    if require_ready and mode == "independent":
        if not meta.get("independent_scoring_ready"):
            raise ValueError("Independent ASA inference/scoring is blocked: original ads, dated evidence and adjudicated references are missing")
        rows = read_rows(root/"runtime/inputs.jsonl")
        if any(not r.get("full_original_ad_available") or not r.get("assessment_cutoff") or not r.get("allowed_evidence_ids") for r in rows):
            raise ValueError("Independent readiness flag is not sufficient: the admitted packet is incomplete")
    return meta


def validate(root, mode):
    meta = assert_runtime_mode(root, mode)
    inputs = read_rows(root/"runtime/inputs.jsonl")
    refs = read_rows(root/"evaluator_only/references.jsonl")
    docs = read_rows(root/"runtime/corpus/passages.jsonl")
    if len(inputs) != EXPECTED_COUNT or [r['example_id'] for r in inputs] != [r['example_id'] for r in refs]:
        raise ValueError("ASA row count or reference alignment failure")
    keyed(inputs, 'inputs'); keyed(refs, 'references'); docmap = _index(docs, 'document_id')
    for row, ref in zip(inputs, refs):
        if set(row) != INPUT_KEYS or row['dataset'] != 'asa' or row['mode'] != mode or ref['reference_mode'] != mode:
            raise ValueError("ASA input allowlist or dataset/mode mismatch")
        if row['example_id'] != row['claim_id']:
            raise ValueError("Native ASA identity changed")
        if ref['draft_material_overstatement'] not in MATERIAL or ref['draft_evidence_status'] not in EVIDENCE:
            raise ValueError("ASA reference label mapping failed")
        if len(row['allowed_evidence_ids']) != len(set(row['allowed_evidence_ids'])):
            raise ValueError("Duplicate ASA evidence references")
        for ident in row['allowed_evidence_ids']:
            if ident not in docmap or docmap[ident]['example_id'] != row['example_id']:
                raise ValueError("ASA evidence ID is missing or belongs to another claim")
    expected_ids = {i for r in inputs for i in r['allowed_evidence_ids']}
    if expected_ids != set(docmap):
        raise ValueError("Unscoped ASA corpus passages")
    for doc in docs:
        if set(doc) != DOC_KEYS or doc['text_sha256'] != hashlib.sha256(doc['text'].encode()).hexdigest():
            raise ValueError("ASA document schema or content hash failed")
        if mode == 'independent' and doc['answer_bearing']:
            raise ValueError("Answer-bearing retrospective evidence in independent packet")
    if mode == 'retrospective' and (not docs or not all(d['answer_bearing'] for d in docs)):
        raise ValueError("Supplied retrospective summaries must retain their answer-bearing marking")
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest['mode'] != mode or manifest['dataset'] != 'asa':
        raise ValueError("ASA manifest mode mismatch")
    for name, expected in manifest['prepared_file_sha256'].items():
        p = root/name
        if not p.resolve().is_relative_to(root.resolve()) or not p.is_file() or digest(p) != expected:
            raise ValueError(f"ASA prepared checksum failed: {name}")
    if meta['evidence_documents'] != len(docs):
        raise ValueError("ASA corpus count mismatch")
    # Reject unexpected files so an accidental answer-key copy cannot silently pass validation.
    actual = {str(p.relative_to(root)) for p in (root/'runtime').rglob('*') if p.is_file()}
    recorded = {s for s in manifest['prepared_file_sha256'] if s.startswith('runtime/')}
    if actual != recorded:
        raise ValueError("Unexpected or missing file in ASA runtime")
    print(f"Validated {len(inputs)} ASA {mode} records; labels separated; mode/provenance/hash checks passed.")


def _target(ref, mode, allow_draft):
    if ref.get('reference_mode') != mode:
        raise ValueError('ASA reference mode mismatch')
    reviewed = ref.get('reviewed_reference_assessment')
    if mode == 'independent':
        if allow_draft:
            raise ValueError('--allow-draft is forbidden for independent ASA evaluation')
        if ref.get('independent_readiness') != 'ready' or not ref.get('allowed_evidence_ids') or not ref.get('full_original_ad_available') or not ref.get('independent_assessment_cutoff'):
            raise ValueError('Independent ASA scoring blocked: incomplete original-ad/evidence/cutoff packet')
    if ref.get('review_status') == 'adjudicated' and isinstance(reviewed, dict):
        if reviewed.get('mode') != mode:
            raise ValueError('ASA adjudication was made for another evidence mode')
        material, status = reviewed.get('material_overstatement'), reviewed.get('evidence_status')
        draft = False
    elif mode == 'retrospective' and allow_draft:
        material, status = ref['draft_material_overstatement'], ref['draft_evidence_status']
        draft = True
    else:
        raise ValueError('ASA references are unreviewed drafts; provisional retrospective scoring requires --allow-draft')
    if material not in MATERIAL or status not in EVIDENCE:
        raise ValueError('Invalid normalized ASA reference labels')
    return material, status, draft


def check_prediction(pred, mode):
    if pred.get('mode') != mode:
        raise ValueError('ASA predictions require mode matching --mode; use import-predictions for native files')
    if pred.get('dataset', 'asa') != 'asa':
        raise ValueError('Wrong dataset in ASA prediction')
    status = pred.get('status', 'ok')
    if status not in ('ok', 'pending', 'abstained', 'error'):
        raise ValueError(f'Invalid prediction status: {status}')
    if not usable(pred):
        return
    if pred.get('material_overstatement') not in MATERIAL or pred.get('evidence_status') not in EVIDENCE:
        raise ValueError('Completed ASA predictions require normalized material_overstatement and evidence_status labels')
    for key in ('explanation', 'supported_rewrite'):
        if pred.get(key) is not None and not isinstance(pred[key], str):
            raise ValueError(f'ASA {key} must be text or null')
    ids = pred.get('evidence_ids', [])
    if not isinstance(ids, list) or any(not isinstance(i, str) or not i for i in ids):
        raise ValueError('ASA evidence_ids must be a list of nonempty strings')
    probabilities = pred.get('probabilities')
    if probabilities is not None:
        if not isinstance(probabilities, dict) or set(probabilities) != set(MATERIAL):
            raise ValueError('ASA probabilities must map exactly present, absent, undetermined')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in probabilities.values()):
            raise ValueError('ASA probabilities must be finite numbers in [0,1]')
        if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-6):
            raise ValueError('ASA probabilities must sum to one')
        if probabilities[pred['material_overstatement']] < max(probabilities.values()) - 1e-9:
            raise ValueError('ASA selected material label must maximize its probability')


def score(pairs, mode, allow_draft=False):
    require_mode(mode)
    if not pairs:
        raise ValueError('Empty ASA evaluation selection')
    # Check ALL selected references, including missing predictions, before grading.
    targets = [_target(r, mode, allow_draft) for r, _ in pairs]
    gs, ps, es, ep, brier, logloss, details = [], [], [], [], [], [], []
    groups = {}
    statuses = Counter()
    valid_citations = cited_count = cited_examples = cited_examples_valid = determinate_correct = determinate = 0
    for (ref, pred), (g, e, _) in zip(pairs, targets):
        if pred is not None:
            check_prediction(pred, mode)
        ok = usable(pred)
        guess = pred['material_overstatement'] if ok else '__MISSING__'
        eguess = pred['evidence_status'] if ok else '__MISSING__'
        gs.append(g); ps.append(guess); es.append(e); ep.append(eguess)
        hit = g == guess
        groups.setdefault(ref.get('company_group', ref['example_id']), []).append(hit)
        statuses['completed' if ok else ('error' if pred and pred.get('error') else pred.get('status', 'error') if pred else 'missing')] += 1
        if ok and guess != 'undetermined':
            determinate += 1; determinate_correct += int(hit)
        evidence_ids = pred.get('evidence_ids', []) if ok else []
        allowed = set(ref['allowed_evidence_ids'])
        invalid = sorted(set(evidence_ids)-allowed)
        valid_citations += sum(i in allowed for i in set(evidence_ids))
        cited_count += len(set(evidence_ids))
        cited_examples += int(bool(evidence_ids)); cited_examples_valid += int(bool(evidence_ids) and not invalid)
        if ok and pred.get('probabilities') is not None:
            prob = pred['probabilities']
            brier.append(sum((prob[k]-int(k == g))**2 for k in MATERIAL))
            logloss.append(-math.log(max(prob[g], 1e-15)))
        details.append({'example_id': ref['example_id'], 'completed': ok,
                        'material_correct': hit, 'evidence_status_correct': e == eguess,
                        'joint_correct': hit and e == eguess, 'invalid_evidence_ids': invalid})
    material = class_metrics(gs, ps, MATERIAL)
    evidence = class_metrics(es, ep, EVIDENCE)
    def ratio(a,b): return a/b if b else None
    n = len(pairs); draft_count = sum(t[2] for t in targets)
    return {
        'metric': 'ASA_project_rubric_comparison_NOT_official_ASA_benchmark', 'n': n,
        'mode': mode, 'reference_status': ('PROVISIONAL_DRAFT_COMPARISON_NOT_BENCHMARK_RESULT' if draft_count else 'ADJUDICATED_REFERENCE_COMPARISON'),
        'draft_reference_count': draft_count, 'independent_detection_evaluated': mode == 'independent',
        'material_accuracy': material['accuracy'], 'material_macro_f1': material['macro_f1'],
        'material_per_class': material['per_class'], 'material_confusion': material['confusion'],
        'evidence_status_accuracy': evidence['accuracy'], 'evidence_status_macro_f1': evidence['macro_f1'],
        'evidence_status_per_class': evidence['per_class'], 'evidence_status_confusion': evidence['confusion'],
        'joint_accuracy': sum(x['joint_correct'] for x in details)/n,
        'prediction_coverage': statuses['completed']/n, 'output_status_counts': dict(statuses),
        'missing_or_failed_ids': [x['example_id'] for x in details if not x['completed']],
        'false_adverse_finding_rate_on_absent': ratio(sum(g == 'absent' and p == 'present' for g,p in zip(gs,ps)), gs.count('absent')),
        'unjustified_determinate_rate_on_undetermined': ratio(sum(g == 'undetermined' and p in ('present','absent') for g,p in zip(gs,ps)), gs.count('undetermined')),
        'determinate_prediction_rate': determinate/n, 'accuracy_among_determinate_predictions': ratio(determinate_correct, determinate),
        'company_macro_accuracy': sum(sum(v)/len(v) for v in groups.values())/len(groups), 'company_group_count': len(groups),
        'probability_examples': len(brier), 'probability_coverage': len(brier)/n,
        'multiclass_brier': ratio(sum(brier), len(brier)), 'log_loss_clipped_1e_15': ratio(sum(logloss), len(logloss)),
        'citation_id_validity_DIAGNOSTIC_ONLY': ratio(valid_citations, cited_count),
        'citation_coverage': cited_examples/n, 'all_cited_ids_valid_on_cited_examples': ratio(cited_examples_valid, cited_examples),
        'evidence_backed_correctness': None, 'explanation_correctness': None, 'supported_rewrite_correctness': None,
        'warning': 'Supplied retrospective summaries contain answers and labels are compiler drafts. Citation-ID matching does not establish entailment. Missing/error/abstained outputs stay in the declared denominator. No deployment calibration or independent detection is established.',
        'details': details,
    }


def template(rows, mode):
    return [{'example_id': r['example_id'], 'dataset': 'asa', 'mode': mode, 'status': 'pending',
             'material_overstatement': None, 'evidence_status': None, 'probabilities': None,
             'explanation': None, 'evidence_ids': [], 'supported_rewrite': None} for r in rows]


def import_native(predictions, inputs, documents, mode):
    require_mode(mode)
    allowed = keyed(inputs, 'inputs')
    docs = {(d['example_id'],d['source_document_id']):d['document_id'] for d in documents}
    output=[]
    for p in predictions:
        ident=p.get('example_id', p.get('claim_id'))
        if ident not in allowed or p.get('claim_id', ident) != ident:
            raise ValueError('Native ASA prediction has an unknown/conflicting claim ID')
        if p.get('mode') not in (None, mode, 'retrospective_explanation' if mode == 'retrospective' else 'independent'):
            raise ValueError('Native prediction has conflicting mode')
        is_pending = p.get('material_overstatement') is None and p.get('evidence_status') is None
        status = p.get('status', 'pending' if is_pending else 'ok')
        row={'example_id': ident, 'dataset':'asa', 'mode':mode, 'status':status,
             'explanation':p.get('explanation'), 'supported_rewrite':p.get('supported_rewrite'), 'evidence_ids':[]}
        if p.get('error'): row['error'] = p['error']
        if status == 'ok' and not row.get('error'):
            row['material_overstatement']=canonical(p.get('material_overstatement'), MATERIAL_MAP, 'material label')
            row['evidence_status']=canonical(p.get('evidence_status'), EVIDENCE_MAP, 'evidence status')
            probabilities=p.get('probabilities')
            if probabilities is not None:
                if not isinstance(probabilities, dict):
                    raise ValueError('Native ASA probabilities must be an object')
                row['probabilities']={canonical(k,MATERIAL_MAP,'probability label'):v for k,v in probabilities.items()}
                if len(row['probabilities']) != len(probabilities):
                    raise ValueError('Duplicate probability labels after normalization')
            for native_id in p.get('evidence_ids', []):
                if native_id in allowed[ident]['allowed_evidence_ids']:
                    row['evidence_ids'].append(native_id)
                elif (ident,native_id) in docs:
                    row['evidence_ids'].append(docs[ident,native_id])
                else:
                    raise ValueError(f'{ident}: unknown supplied evidence ID {native_id!r}')
        check_prediction(row,mode); output.append(row)
    keyed(output,'predictions')
    return output


def export_native(pairs, documents, mode):
    back_m={v:k for k,v in MATERIAL_MAP.items()}; back_e={v:k for k,v in EVIDENCE_MAP.items()}
    docs={d['document_id']:d['source_document_id'] for d in documents}
    output=[]
    for ref,p in pairs:
        if p is None or not usable(p):
            raise ValueError('Native ASA export requires every selected prediction completed; use the shared scorer to retain failures in its denominator')
        check_prediction(p,mode)
        if set(p.get('evidence_ids', []))-set(ref['allowed_evidence_ids']):
            raise ValueError('Cannot export invalid or cross-claim evidence IDs')
        out={'claim_id':ref['example_id'], 'material_overstatement':back_m[p['material_overstatement']],
             'evidence_status':back_e[p['evidence_status']], 'explanation':p.get('explanation'),
             'evidence_ids':[docs[i] for i in p.get('evidence_ids',[])]}
        if p.get('probabilities') is not None:
            out['probabilities']={back_m[k]:v for k,v in p['probabilities'].items()}
        output.append(out)
    return output


def review_sheet(path, pairs, inputs):
    lookup=keyed(inputs,'inputs')
    path.parent.mkdir(parents=True,exist_ok=True)
    fields=['example_id','company_group','campaign_group','mode','claim','context_paraphrase',
            'draft_material_overstatement','draft_evidence_status','reference_is_unreviewed',
            'model_material_overstatement','model_evidence_status','model_explanation','model_evidence_ids',
            'model_supported_rewrite','allowed_evidence_ids','reviewer_1_material','reviewer_1_evidence_status',
            'reviewer_2_material','reviewer_2_evidence_status','adjudicated_material','adjudicated_evidence_status',
            'explanation_correct','citations_entail','rewrite_supported','reviewer','notes']
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r,p in pairs:
            p=p or {}; x=lookup[r['example_id']]
            w.writerow({'example_id':r['example_id'],'company_group':r['company_group'],
                'campaign_group':r['campaign_group'],'mode':r['reference_mode'],'claim':x['claim'],
                'context_paraphrase':x['context_paraphrase'],'draft_material_overstatement':r['draft_material_overstatement'],
                'draft_evidence_status':r['draft_evidence_status'],'reference_is_unreviewed':r['review_status']!='adjudicated',
                'model_material_overstatement':p.get('material_overstatement'),'model_evidence_status':p.get('evidence_status'),
                'model_explanation':p.get('explanation'),'model_evidence_ids':json.dumps(p.get('evidence_ids',[])),
                'model_supported_rewrite':p.get('supported_rewrite'),'allowed_evidence_ids':json.dumps(r['allowed_evidence_ids'])})
