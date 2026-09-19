# Validation report — v1.1 ASA integration

Validation date: 2026-09-19. These are **software/data-transformation checks**, not model benchmark results.

## Executed in this session

| Check | Result | Evidence |
|---|---|---|
| Existing v1.0 unit suite before changes | 47 tests passed | Existing behavior baseline; original adapters/scorers retained |
| Combined v1.1 unit suite | **95 tests passed** (47 existing + 48 ASA tests) | `validation/unit_tests_v1_1.txt` |
| ASA CLI checks | **30 checks passed** | `validation/asa_cli_checks.json` and `.txt` |
| Original uploaded ASA scorer unit tests | **10 tests passed** | `validation/original_asa_scorer_tests.txt` |
| Python compilation | Passed | `compileall` on modules, adapters, tests, and smoke script |
| Uploaded source archive | Exact SHA256 match | `95119566d269a3194bff913fda98cb65f9a461a9e53dcf99ee0d0b871d8f3157` |
| Source member hashes | All listed hashes matched | Checked while preparing from the uploaded archive |
| Normalized ASA identity | 30 unique claim IDs, 24 ruling IDs, 23 company groups | Both modes align to the same original claims |
| Citation identifiers | 30 unique namespaced summary IDs | Avoided collisions across assertion-specific views |
| Retrospective packet | 30 inputs, 30 short answer-bearing summaries | Explicitly labeled retrospective |
| Independent packet | 30 inputs, 0 evidence documents | Run/score blocked; exported only as candidates |
| Readiness flags | 0 adjudicated references, 0 independent-ready cases | Source limits preserved |
| Native prediction round trip | Passed on explicit draft-identity fixtures | Not inference and not evidence of source-label accuracy |
| Original/local scorer agreement | Common full-coverage accuracies agreed on identity fixture | Part of 30 CLI checks; not an official benchmark result |
| Runtime-only export | One mode only; no reference files | Independent corpus empty and no ruling URLs in independent inputs |

A draft-identity fixture deliberately copies reference labels to test mapping/scoring. It does **not** measure a model's ability to predict them. Such fixture predictions are temporary and not bundled as purported model outputs.

The supplied ASA adapter was run only as a request-builder/abstention check. It loaded one allowed summary per example and made no model calls. Native `undetermined` labels remain distinct from operational abstentions.

## What was not done

No live model inference, paid provider calls, upstream public-data downloads, full original-ad collection, historical source verification, independent evidence admission, new adjudication, clinical/legal fact review, calibration fitting, or actual Counterbloat repository integration was executed.

The FinQA, FinanceBench, and AVeriTeC downloader/evaluator code is preserved and covered by existing offline regression tests. Their full online preparation and official benchmark runs remain unexecuted in this update. The prior version's logs are retained under `validation/v1_0/` and documentation under `docs/history/`; do not mistake them for new live runs.

The original ASA review workbook is preserved, unmodified, inside the bundled source archive. No new spreadsheet adjudications or inferred labels were inserted.

## Reproduction

```bash
python -m unittest discover -s tests -v
python validation/run_asa_smoke.py
python benchmark.py validate --dataset asa --mode retrospective
python benchmark.py validate --dataset asa --mode independent
```

The smoke script performs local tests and explicitly marked synthetic identity/abstention checks only. It creates temporary files and refreshes its validation logs. It does not call external APIs. A real system adapter and an appropriately scoped evidence/reference protocol are still required for performance claims.
