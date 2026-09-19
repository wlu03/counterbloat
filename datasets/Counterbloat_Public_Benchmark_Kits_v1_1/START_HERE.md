# Start here — v1.1, ASA added

The **ASA data are already prepared and included**. FinQA, FinanceBench, and AVeriTeC retain their previous pinned downloader workflows; their data are **not** preloaded.

```bash
python benchmark.py validate --dataset asa --mode retrospective
python benchmark.py template --dataset asa --mode retrospective --output outputs/asa.template.jsonl
```

Connect your model through `predict(example, runtime_dir)` as before. Then:

```bash
python benchmark.py run --dataset asa --mode retrospective --adapter my_adapter:predict --output outputs/asa.predictions.jsonl
python benchmark.py score --dataset asa --mode retrospective --allow-draft --predictions outputs/asa.predictions.jsonl --output outputs/asa.metrics.json
```

**The 30 ASA references are compiler drafts. Scoring is provisional retrospective agreement, not independent detection accuracy.** Independent candidate inputs are supplied separately, with no evidence documents; independent run/score is blocked.

Read `guides/ASA.md`, `PREDICTION_FORMAT.md`, and `THIRD_PARTY_NOTICES.md`. `example_asa_adapter:predict` deliberately abstains and makes no paid calls. Python 3.10+; no extra dependencies for ASA preparation or scoring.
