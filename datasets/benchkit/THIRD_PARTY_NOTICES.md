# Sources, attribution, and terms

The code in this kit is a new preparation/evaluation harness. Dataset files, original reports, and upstream evaluators retain their respective authorship and licenses. FinQA, FinanceBench, and AVeriTeC bytes are downloaded from the upstream sources, not bundled here. Version 1.1 additionally preserves and normalizes the user-uploaded ASA archive under the notices below.

## FinQA

Authors: Zhiyu Chen, Wenhu Chen, Charese Smiley, Sameena Shah, Iana Borova, Dylan Langdon, Reema Moussa, Matt Beane, Ting-Hao Huang, Bryan Routledge, William Yang Wang.

Paper: *FinQA: A Dataset of Numerical Reasoning over Financial Data*, EMNLP 2021. https://arxiv.org/abs/2109.00122

Repository: https://github.com/czyssrs/FinQA

Pinned revision: `0f16e2867befa6840783e58be38c9efb9229d742`.

The repository carries an MIT license. Preparation attempts to download and retain its exact LICENSE and README. Preserve the license with copied upstream code/data. The public labeled `test.json` is distinct from the private challenge test. Original corporate-report rights are separate.

## FinanceBench

Authors: Pranab Islam, Anand Kannappan, Douwe Kiela, Rebecca Qian, Nino Scherrer, Bertie Vidgen.

Paper: *FinanceBench: A New Benchmark for Financial Question Answering*. https://arxiv.org/abs/2311.11944

Repository: https://github.com/patronus-ai/financebench

Dataset card and license declaration: https://huggingface.co/datasets/PatronusAI/financebench

Pinned repository revision: `cc39aeb4afdf33909ee1412188bf89035950c2eb`.

The public dataset is marked CC BY-NC 4.0. Use is subject to that license; publicly available does not imply unrestricted commercial reuse. This kit downloads the public 150-example sample, not the full 10,231-question collection. The code's report downloader preserves original PDFs; do not assume the dataset license grants new rights over third-party reports.

## AVeriTeC

Authors: Michael Schlichtkrull, Zhijiang Guo, Andreas Vlachos.

Paper: *AVeriTeC: A Dataset for Real-world Claim Verification with Evidence from the Web*, NeurIPS 2023 Datasets and Benchmarks. https://arxiv.org/abs/2305.13117

Official download page: https://fever.ai/dataset/averitec.html

The official page links the FEVER-7 Hugging Face release at https://huggingface.co/chenxwh/AVeriTeC

Pinned release: `2ca9dee23a2a6fa64c5bd918e0cd28ed0aa09031`.

License: CC BY-NC 4.0. https://creativecommons.org/licenses/by-nc/4.0/

This kit intentionally uses the matched **FEVER-7 dev data, dev knowledge store, and FEVER-7 evaluator**, not the newer FEVER-8/AVeriTeC 2.0 test protocol. It prepares 500 development claims for declared local evaluation. It does not claim they are a blind official test. Keep the original row order for per-claim corpus alignment. External source content retains its original rights.

## Change notice and evaluation boundaries

The preparation step produces a transformed, allowlisted model-input view and a separate gold-reference view. Native original rows are retained under `evaluator_only/`. Stable local IDs are added; the documented AVeriTeC label spelling alias is normalized for the local scorer. No claims or examples are generated and relabeled as official test data.

The optional oracle export is an additional view of annotated evidence, not a new official split. All tests shipped with this kit use fictional fixtures; they are not real company statements and are not mixed into prepared public datasets.

Do not remove attribution or apply the kit code's license to the datasets. Obtain appropriate permissions before uses outside the applicable data/source licenses.

## ASA user-supplied pack — added in v1.1

Source: user-uploaded `ASA_test_pack_2026-09-19(1).zip`, internal version 0.1.0, compiled 2026-09-19. Not redistributed here; the normalized packets under `../asa/` derive from it. SHA256 `95119566d269a3194bff913fda98cb65f9a461a9e53dcf99ee0d0b871d8f3157`.

The original README/manifest and review workbook are in that upload, which is not included here. The source supplies short claim excerpts and compiler paraphrases, not a republication license for full rulings, original advertisements, or studies. ASA and relevant third parties retain rights in their materials. This integration does not extend the kit-code license to the source data, establish permission for broader redistribution, or represent endorsement by ASA. Consult the preserved source notices before reuse or publication.

The normalized fields and local scorer do not independently validate the compiler's factual interpretations. The source's draft labels remain drafts. No original advertisements or new independent evidence have been collected as part of this update.
