# FinanceBench test guide

## Scope

Prepare the **150-example public sample** and document metadata from the pinned official repository. This is not the full private collection or a separate official test split. Reserve it as a local holdout. The task is financial-report question answering, not direct corporate-overstatement classification.

The dataset is marked **CC BY-NC 4.0** on its official Hugging Face card; underlying report rights are separate. Read `THIRD_PARTY_NOTICES.md` before accepting terms.

## Download labels/questions, then original reports

```bash
python benchmark.py prepare --dataset financebench --accept-license
python benchmark.py validate --dataset financebench

# Preview document count and size; no large PDF downloads yet.
python benchmark.py corpus --dataset financebench --accept-license

# Explicitly download the original report collection and create page text.
python -m pip install -r requirements-corpus.txt
python benchmark.py corpus --dataset financebench --accept-license --confirm-large-download --extract
```

The corpus downloader discovers PDFs from the complete pinned Git tree, checks each Git blob hash, rejects non-PDF responses, and records a corpus manifest only after successful completion. It does not silently call a partial collection complete. Original PDFs are retained. PyMuPDF page text may lose table layout; inspect original pages for important numerical discrepancies. The kit does not configure Elasticsearch for you.

## Model input and evidence

Model inputs contain `example_id`, `question`, `company`, and the designated `doc_name`. Report metadata and downloaded original pages are runtime resources. No answer, justification, gold evidence snippet, or annotated evidence page is in the normal input.

Choose and disclose a document-scoped or corpus-wide retrieval protocol. Some questions need multiple passages or periods; do not narrow using the gold evidence. Generated page records use physical **zero-based `page_index`**, matching the benchmark annotation convention, not printed page labels.

Return:

```json
{"example_id":"ID_FROM_INPUT","status":"ok","answer":"The system's answer","citations":[{"doc_name":"DOCUMENT_ID","page_index":0}]}
```

See `PREDICTION_FORMAT.md` for the common contract. `my_adapter:predict` must call your actual QA/retrieval pipeline. It is not supplied as a fake high-performing model.

```bash
python benchmark.py run --dataset financebench --adapter my_adapter:predict --output financebench.predictions.jsonl
python benchmark.py score --dataset financebench --predictions financebench.predictions.jsonl --output financebench.diagnostics.json
```

## Human correctness and evidence review

Exact string matching is a diagnostic only. Different correct explanations can use different words, and identical-looking numbers may have different units. Annotated-page overlap does not establish citation entailment.

```bash
python benchmark.py review-sheet --dataset financebench --predictions financebench.predictions.jsonl --output financebench.review.csv
```

The CSV contains answers and evidence: keep it evaluator-only. Fill the following with `1` (yes) or `0` (no), and provide reviewer/notes:

- `answer_correct`: correct and responsive, with correct numerical units, periods, and scope.
- `citation_supported`: the cited original passages support the answer.
- `evidence_sufficient`: the citations collectively establish all material parts of the answer.

Leave unreviewed rows blank; do not pre-fill success. Review blinded to system configuration where possible and adjudicate disagreements.

```bash
python benchmark.py score --dataset financebench --predictions financebench.predictions.jsonl --reviews financebench.review.csv --output financebench.reviewed_scores.json
```

The kit reports reviewed-set coverage and accuracy separately. Full-set human answer accuracy remains null until every declared example is reviewed. Error/missing predictions stay in the denominator; a positive review cannot turn a missing output into a correct answer.

## Optional oracle interpretation test

```bash
python benchmark.py oracle --dataset financebench --acknowledge-oracle --output oracle/financebench.inputs.jsonl
```

This creates explicit annotated-evidence inputs outside `runtime/`. Evaluate them with a separate oracle-aware caller; the default `run` command reads normal `runtime/inputs.jsonl` only. Report oracle results separately from retrieval. The native result includes available reference snippets, not a complete report corpus.
