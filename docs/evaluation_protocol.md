# Evaluation protocol

No evaluation has been run. This file states how to run one.

1. Import each dataset with its adapter in `datasets/adapters/` and record a manifest with
   `datasets/manifests/manifest.py` (file hash, row count, revision, license, field mapping).
2. Export with `datasets.adapters.base.export`. It writes model inputs and gold labels to separate
   files. Put the gold file in `gold/`, which the worker does not read and git ignores.
3. Use `config/evaluation.yaml`: frozen mode, no external discovery.
4. Use each dataset for its own task: claim detection (environmental_claims), question-based
   verification (AVeriTeC), numerical programs (FinQA), document question answering (FinanceBench),
   case review (GreenClaims). Do not relabel any of them as overstatement labels.
5. Compare systems A0 to A5 from `evaluation/ablations/` on the same cases and the same retrieval
   budget. For compression comparisons, freeze the retrieved passages first.
6. Report the metrics in `evaluation/components/metrics.py`. Selective error is undefined when no
   case is accepted. Report cost from the run manifest, including failed calls and fallbacks.
7. Keep demo cases out of the test set. Lock the configuration before scoring the test set.

`uv run pytest` covers the deterministic checks: arithmetic on the fictional emissions example,
duplicate evidence, withdrawal, ordering, cutoff admissibility, protected-text retention, quote
validation, and blocked fetch destinations.
