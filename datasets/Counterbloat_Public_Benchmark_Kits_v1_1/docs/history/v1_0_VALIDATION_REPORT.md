# Validation report

Prepared on 2026-09-19. This report describes testing of the **kit**, not accuracy of Counterbloat or any model.

## Executed successfully

| Check | Result |
|---|---|
| `python -m unittest discover -s tests -v` | **47 passed** |
| Synthetic command-line workflows | **3 dataset workflows, 25 CLI command invocations passed** |
| Python compilation | `benchmark.py`, `example_adapter.py`, `benchkit/`, and `tests/` compiled successfully |
| Final ZIP validation | Each archive is checked for CRC errors, accidental Python caches, and absent intended files during packaging |

The unit tests cover exact input allowlists, gold-field separation, ID/count failures, scalar and program validation, missing-prediction denominators, label/probability checks, local FinanceBench review metrics, mocked downloads, archive safety, and runtime-only export boundaries.

The synthetic CLI workflows exercise subset selection, pending templates, the explicitly abstaining adapter, diagnostic scoring, official-format export, runtime-only export, FinanceBench review CSV generation, oracle mode, and expected rejection of unsafe paths or prediction overwrite. They use one fictional fixture per dataset, not public benchmark rows. FinQA smoke scoring uses the nonofficial answer-only diagnostic; no official scorer was executed.

Testing was performed on Python 3.13 in this environment. The code targets Python 3.10+ but was not run across every supported interpreter or operating system.

## Not executed or established

- Full original dataset downloads or successful `prepare` on those full releases. Container network/file-materialization attempts failed; the ZIPs do not include public dataset bytes.
- Actual FinQA, FinanceBench, or AVeriTeC model inference or accuracy results.
- Complete official FinQA program-equivalence or AVeriTeC evidence-conditioned scoring runs.
- Real API calls, paid experiments, repository integration, or Elasticsearch indexing.
- Download or extraction of FinanceBench report PDFs or the approximately 11.5 GB AVeriTeC archive.
- Human grading of FinanceBench outputs, citation entailment, or real corporate-overstatement annotations.
- Empirical calibration, dataset-contamination removal, or historical evidence admissibility.

Upstream source locations, revisions, example schemas, license information, and scorer interfaces were inspected through available web/GitHub tools. The downloader is designed to fetch pinned releases and fail on hash/count/schema problems, but the complete online workflow must still be run and validated on the user's machine.

## Reproduce local kit tests

```bash
python -m unittest discover -s tests -v
python -m compileall -q benchmark.py example_adapter.py benchkit tests
```

Unit-test output is preserved in `validation/unit_tests.txt`. CLI smoke output is in `validation/cli_smoke_checks.txt`; temporary paths in that log are from disposable synthetic fixtures and do not refer to bundled dataset files.

Do not cite kit-test pass counts as model benchmark performance.
