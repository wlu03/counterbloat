"""The earnings call workflow behind the reader: which calls can be run, and what a run produced.

A call is runnable only when every part the workflow needs is present: the transcript with its
speaker labels, the annual report for the same period, and the figures the company filed. Those
are the traces recorded by the corpus check, so this reads them rather than deciding again.
"""
from __future__ import annotations

import json
from pathlib import Path

TRACES = Path("results/complete_traces.json")
SOURCE = "MAEC aligned earnings call corpus"
# The audio in this corpus was recorded between these years and does not extend past them.
AUDIO_VINTAGE = "2015-2018"
# The verdicts the pipeline reports, in the words the reader uses.
VERDICTS = {"contradicted": "overstated", "consistent": "supported", "abstain": "abstain"}


def _period(date: str) -> str:
    """A call reports the quarter before the one it is held in."""
    year, month = int(date[:4]), int(date[5:7])
    quarter = (month - 1) // 3 or 4
    return f"{year if quarter != 4 else year - 1} Q{quarter}"


def catalogue(traces: Path | str = TRACES) -> list[dict]:
    """Every call the workflow can run, newest first. An absent file means none are prepared."""
    path = Path(traces)
    if not path.is_file():
        return []
    rows = json.loads(path.read_text())
    out = []
    for row in rows:
        out.append({
            "id": row["call"], "ticker": row["ticker"], "company": row["ticker"],
            "sector": "other", "period": _period(row["date"]), "callDate": row["date"],
            "cik": row["cik"], "docs": ["transcript", "10-K", "audio"],
            "executiveCount": 0, "analystCount": 0, "wordCount": 0,
            "source": SOURCE, "audioVintage": AUDIO_VINTAGE,
            "summary": (f"{row['ticker']} call of {row['date']}, checked against the annual "
                        f"report filed as {row['tenk']}."),
            "accession": row["tenk"], "sourceUrl": row["tenk_url"],
        })
    return sorted(out, key=lambda r: r["callDate"], reverse=True)


def as_ledger(call_id: str, rows: list[dict], sentences: int) -> dict:
    """Turn the rows one run produced into the shape the reader reads.

    `probability` is the accumulated score when a scorer weighed the findings, and null when
    none did. `calibrated` stays false either way: nothing is fitted to an outcome, and of the
    claims read so far only a handful could be settled against a filed figure, none of which
    disagreed. The number says how the evidence adds up, not how often such a claim is wrong.
    """
    claims = []
    for row in rows:
        gap = row.get("evidence_gap")
        claims.append({
            "id": row["claim_id"], "text": row["claim"], "speaker": row.get("speaker") or "",
            "segment": row.get("segment") or "prepared", "claimType": row["claim_type"],
            "topic": row.get("metric") or "",
            "specificity": row["specificity"],
            "hedgingDelta": row.get("parts", {}).get("gap.hedging_delta", 0.0),
            "rhetoricalInflation": round(100 * row["rhetorical_inflation"], 1),
            "evidenceGap": None if gap is None else round(100 * gap, 1),
            "probability": row.get("probability"),
            "probabilityBasis": row.get("probability_basis", []),
            "verdict": VERDICTS.get(row["verdict"], "abstain"),
            "evidence": [{
                "agent": e["agent"], "tier": e["tier"], "stance": e["stance"],
                "span": e.get("quote") or e.get("note"),
                "accession": e.get("accession"),
                "matchScore": e.get("score") or e.get("similarity") or 0.0,
            } for e in row.get("evidence", [])],
        })
    abstained = sum(1 for c in claims if c["verdict"] == "abstain")
    return {
        "transcriptId": call_id, "claims": claims, "extractedSentences": sentences,
        "claimsFound": len(claims),
        "evidenceItems": sum(len(c["evidence"]) for c in claims),
        "abstainRate": round(abstained / len(claims), 3) if claims else 0.0,
        "calibrated": False,
        "calibrationNote": ("no curve is fitted: too few claims can be settled against a "
                            "filed figure, and none of those disagreed"),
    }


def run_workflow(call_id: str, store, deps, span_limit: int = 12) -> dict:
    """Read one call end to end and store the ledger it produced.

    Imported inside the function because the workflow pulls in the corpus reader, the filing
    parser and the providers, none of which the rest of the API needs.
    """
    from backend.claims.extract import extract
    from backend.ingestion import transcript
    from backend.ingestion.edgar import cik_for
    from backend.ingestion.fetch import fetch
    from backend.ingestion.parse import parse
    from backend.ingestion.sections import sections
    from backend.models import Mode, RunManifest
    from backend.orchestration.overstatement import as_dicts, company_spans, row_for

    record = next((c for c in catalogue() if c["id"] == call_id), None)
    if record is None:
        raise LookupError(f"no prepared call {call_id}")
    dataset = Path(corpus_root()) / "MAEC_Dataset"
    labels = Path(corpus_root()) / "MAEC_Dataset_Person_Label"
    sentences = transcript.read_call(dataset, call_id, labels)
    speakers = transcript.speakers_in_prepared(sentences)
    _, spans = transcript.spans(sentences)
    turns = transcript.turns(sentences)
    chosen = company_spans(spans, sentences, speakers, min_chars=100)[:span_limit]

    manifest = RunManifest(analysis_id=call_id, mode=Mode.live, config_hash="workflow")
    llm = deps.llm_factory(manifest)
    claims = extract(chosen, llm, None, manifest, id_prefix=f"{record['ticker']}-", workers=8)
    content, media, _ = fetch(record["sourceUrl"])
    _, filing_spans, _ = parse(record["accession"], content, media)
    filing = sections(filing_spans)
    cik, period = cik_for(record["ticker"]), record["period"].replace(" ", "-")
    by_index = {s.index: s for s in sentences}
    rows = []
    for claim in claims:
        sentence = by_index[int(claim.span_id.split(":")[1])]
        rows.append(row_for(
            claim, speaker=sentence.speaker, segment=sentence.segment, cik=cik, sections=filing,
            period=period, accession=record["accession"], source_url=record["sourceUrl"],
            turn=next((t.text for t in turns if claim.text in t.text), None),
            call_date=record["callDate"], scorer=llm, manifest=manifest, embed=llm.embed))
    ledger = as_ledger(call_id, as_dicts(rows), sentences=len(sentences))
    ledger["status"] = "done"
    ledger["errors"] = manifest.errors
    store.put("call_runs", call_id, ledger)
    return ledger


def corpus_root() -> str:
    """Where the aligned call corpus was unpacked."""
    import os
    return os.environ.get("MAEC_ROOT", str(next(
        Path("datasets/maec/source").glob("MAEC-*"), Path("datasets/maec/source"))))
