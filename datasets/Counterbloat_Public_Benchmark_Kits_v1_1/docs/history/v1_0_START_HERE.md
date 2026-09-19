# Start here: combined public benchmark kit

**Dataset bytes are not bundled.** This kit downloads pinned official sources on your machine. Read `THIRD_PARTY_NOTICES.md`, then:

```bash
python benchmark.py prepare --dataset finqa --accept-license
python benchmark.py prepare --dataset financebench --accept-license
python benchmark.py prepare --dataset averitec --accept-license
```

Use the corresponding guide under `guides/` for source-corpus downloads, your model adapter, and scoring. The 11.5 GB AVeriTeC development corpus and FinanceBench original PDFs need a separate explicit download. FinQA's native text/table excerpts are prepared with its test file.

Read `README.md`, `PREDICTION_FORMAT.md`, and `VALIDATION_REPORT.md`. No actual model benchmark scores are included.
