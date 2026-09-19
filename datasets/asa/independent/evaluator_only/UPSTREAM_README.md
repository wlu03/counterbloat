# ASA assertion-level starter test pack

**Version 0.1.0 — compiled 19 September 2026**

This pack contains **30 assertion-level records from 24 ASA rulings**. It is a manually compiled, purposive starter selection, not the complete 198-ruling past-year search pool, not a random sample, and not the proposed balanced 100-case evaluation. It includes historical rulings alongside recent cases. ASA did not create, review, or endorse this pack.

## What you can test now

**Retrospective interpretation:** Feed `data/retrospective_inputs.jsonl` to your system, one record per request, using `prompts/retrospective.txt`. Each record includes a short, answer-bearing compiler paraphrase of the ASA assessment. This is useful for testing whether the system explains the documented scope, comparison, or qualification issue and produces the required output. It is not independent detection, nor a test of extracting facts from a full ruling.

**Ingestion and collection:** `data/claim_inputs.jsonl` is a label-free candidate list. It contains short claim excerpts, paraphrased context, company/product, and observed-date information. It deliberately excludes ruling URLs, decisions, reference labels, mechanisms and assessment summaries. It has **zero admitted independent evidence documents** and must not be scored against the retrospective draft labels.

No model endpoint was supplied or run. File validation and synthetic tests of the included scorer are not model performance results.

## Download contents

| File | Purpose | Give it to the model? |
|---|---|---|
| `ASA_review_workbook.xlsx` | Six review sheets: overview, claims, rulings, evidence, human review, rubric | No in independent mode; it contains answers |
| `data/claim_inputs.jsonl` and `.csv` | Label-free candidates; all independent packets incomplete | For ingestion or after evidence curation |
| `data/retrospective_inputs.jsonl` | Claim plus short answer-bearing assessment paraphrase | Yes, only in retrospective mode |
| `evaluator/reference_drafts.jsonl` | Native issue findings, draft project labels, provenance, grouping and collection gaps | Evaluator only |
| `evaluator/claims_with_draft_labels.csv` | Flat, spreadsheet-friendly version of the curator records | Evaluator only |
| `evaluator/rulings.csv` | One entry per ruling, with source URL | Evaluator only |
| `evaluator/evidence_register.csv` | Ruling references and two unadmitted research-paper leads | Curator only |
| `review/review_template.csv` | Blank reviewer 1, reviewer 2 and adjudication fields | Reviewers only |
| `predictions.template.jsonl` | Empty prediction rows keyed by claim ID | Fill with model outputs |
| `schema/prediction.schema.json` | Output schema | Yes |
| `scripts/score.py` | Strict JSONL scoring and readiness checks; standard library only | Run locally |
| `scripts/test_score.py` | Synthetic unit tests of scorer behavior | Run locally |
| `validation_report.json` | File, leakage-field and scorer checks | Informational |

## Draft labels, not gold labels

The compiler's provisional material-overstatement distribution is:

| Label | Assertions |
|---|---:|
| Present | 20 |
| Absent | 7 |
| Undetermined | 3 |

These are **project-rubric interpretations of the retrospective ASA record**, not native ASA classifications. All `reviewed_reference_assessment` values are `null`. No two-reviewer agreement or adjudication has been performed. The distribution is not a prevalence estimate or balanced evaluation sample.

The two dimensions are independent:

- Material overstatement: `Present`, `Absent`, `Undetermined`.
- Evidence status: `Supported`, `Contradicted`, `Mixed`, `Insufficient`, `Not yet resolvable`.

A supported number may have misleading advertised scope. Missing evidence does not prove the opposite. A regulator can uphold a complaint because substantiation was absent, even when this rubric leaves the exact factual assertion unresolved. Mechanisms on unresolved rows are hypotheses, not established findings.

Keep ruling-level decisions and issue-level findings separate. Multiple issues can concern one assertion. The files preserve the native outcome of each selected issue rather than splitting one assertion into contradictory positive and negative copies. Not every issue in each ruling is represented: unrelated regulatory issues are outside the chosen target.

## Run a retrospective smoke test

1. Read `prompts/retrospective.txt` as the task instruction.
2. Send each record in `data/retrospective_inputs.jsonl` to your system. Keep the `claim_id` unchanged.
3. Save one output object per line to `predictions.jsonl`, matching the schema. The template's `null` labels are placeholders and intentionally fail scoring until filled.
4. Run from the unpacked folder:

```bash
python scripts/test_score.py
python scripts/score.py \
  --predictions predictions.jsonl \
  --mode retrospective \
  --allow-draft \
  --output metrics.json
```

`--allow-draft` is required because this release has no adjudicated references. The result is labeled a **provisional draft comparison**, not a benchmark result. Without the flag the scorer refuses to treat drafts as gold. It also refuses independent scoring for all supplied records.

Example output shape (illustrative values, not a case answer):

```json
{
  "claim_id": "COPY_THE_INPUT_CLAIM_ID",
  "material_overstatement": "Undetermined",
  "evidence_status": "Insufficient",
  "probabilities": {"Present": 0.15, "Absent": 0.10, "Undetermined": 0.75},
  "explanation": "Explain what the admitted record establishes and what remains unresolved.",
  "evidence_ids": ["COPY_A_SUPPLIED_DOCUMENT_ID"]
}
```

Probabilities are optional. When supplied, they must sum to one and the selected class must maximize its probability. The scorer reports material accuracy, evidence-status accuracy, class precision/recall/F1, false accusations on negative references, determinate answers on unresolved references, company-macro accuracy and an optional three-class Brier score. It does **not** grade explanation quality, verify cited passages, measure calibration reliability, or estimate deployment performance. Missing predictions fail by default; `--allow-partial` makes coverage explicit rather than silently dropping failures.

## What is still missing for independent detection

All 30 records are blocked for independent scoring. No original full ad or date-frozen substantiation packet has been captured. The model-visible text is reconstructed from descriptions in rulings: short quoted claim excerpts plus compiler paraphrases of surrounding context. These are **not verbatim full advertisements**. Images, font prominence, video timing and complete qualifications have not been reproduced. One record identifies an implied claim from address/domain presentation rather than a literal declarative sentence.

A claim's `observed_date` is not necessarily its first-publication date. Month-only dates retain month precision; no day is invented. OneStream's observation has no verified year, so its normalized date is `null`. Independent cutoffs are deliberately unset rather than silently defaulted to a later ruling date. Retrospective cutoffs are the publication dates of the rulings.

For each independent case:

1. Capture and verify the original ad and surrounding qualifications. Preserve prominence or restrict the evaluation claim to what text-only inputs can establish.
2. Set an explicit assessment cutoff. Identify dated evidence actually available by that cutoff; later regulator evidence does not automatically qualify.
3. Retrieve underlying documents, not accusation summaries. Record publication/version dates and admissibility. The two research-paper URLs are leads only: their relevant complete methods and results were not captured and they are not admitted evidence.
4. Have two reviewers assess the same admitted packet the model will see. Record individual labels and notes, resolve disagreement, and preserve genuinely unresolved cases.
5. Export a new version with `independent_readiness: "ready"`, a nonempty admitted evidence packet, `review_status: "adjudicated"` and an evidence-conditioned `reviewed_reference_assessment` for mode `independent`. Changing a readiness flag alone is not sufficient curation.

The review worksheet does not automatically update the JSONL references. After adjudication, merge the review decisions and finalized evidence IDs into a versioned reference file. The scorer accepts `--references path/to/reviewed_references.jsonl`.

Example adjudicated reference structure:

```json
{
  "review_status": "adjudicated",
  "reviewed_reference_assessment": {
    "mode": "independent",
    "material_overstatement": "Present",
    "evidence_status": "Mixed",
    "evidence_packet_id": "YOUR_FROZEN_PACKET_ID",
    "adjudication_notes": "YOUR_REVIEWED_REASONING"
  }
}
```

## Leakage, grouping and limitations

Ruling URLs and assessment text are answer-bearing. Do not supply the workbook, evaluator directory, retrospective inputs, or this README to a model during an independent test. Even the label-free file is derived from a ruling's account of the ad, so source reconstruction can introduce selection and wording effects. Public company names and claims may also be memorized by pretrained models. No contamination-free status is claimed.

Use `company_group` and `campaign_group` when defining future splits. Keep linked company/campaign groups together, including related Shell rulings and the cluster of hotel environmental-description cases. No train/dev/test split is supplied because this small collection is diagnostic, not a generalization benchmark.

The pack deliberately distinguishes specific accepted assertions from broader misleading impressions. An absent label is bounded to the selected issue/context, not an independent audit of the company. Claims involving health are advertising-evaluation examples, not medical advice. Regulatory outcomes are quoted as case-specific historical decisions, not legal advice or independent allegations of fraud.

## Sources and reuse

Each curator row contains its ASA source URL and assessment-section locator. The evidence register distinguishes material read through the ruling from uncollected original evidence. Short excerpts and compiler-written paraphrases are supplied instead of full copyrighted rulings or advertisements. ASA and third parties retain any rights in their materials; no permission to republish original ads, full rulings or company records is asserted. Check permissions before publishing an expanded dataset.
