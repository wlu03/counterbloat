"""ASA request builder and deliberately abstaining integration adapter.

No LLM is called. Replace predict() with your real system integration; build_request
supplies the standardized claim and its permitted, assertion-scoped passages.
"""
from pathlib import Path
from .io import read_rows


def build_request(example: dict, runtime_dir: Path) -> dict:
    if example.get('dataset') != 'asa' or example.get('mode') != 'retrospective':
        raise ValueError('This template is for the supplied ASA retrospective packet only')
    allowed=set(example['allowed_evidence_ids'])
    evidence=[d for d in read_rows(runtime_dir/'corpus/passages.jsonl')
              if d['example_id']==example['example_id'] and d['document_id'] in allowed]
    if {d['document_id'] for d in evidence} != allowed:
        raise ValueError('An allowed evidence document is missing')
    return {'example':example, 'evidence':evidence,
            'instruction':'Interpret the provided historical assessment summary. Preserve qualifications. '
                'Return material_overstatement and evidence_status using the documented schema. '
                'This is retrospective summary interpretation, not independent claim verification.'}


def predict(example: dict, runtime_dir: Path) -> dict:
    request=build_request(example,runtime_dir)
    # Replace with a real model call. Never load evaluator_only or copy draft labels.
    return {'status':'abstained','reason':'No model is connected; request construction was checked.',
            'request_evidence_count':len(request['evidence'])}
