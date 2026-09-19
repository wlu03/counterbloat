"""Release references checked on 2026-09-19. Original three dataset downloads remain external; uploaded ASA bytes are bundled."""
FINQA_REV = "0f16e2867befa6840783e58be38c9efb9229d742"
FINANCE_REV = "cc39aeb4afdf33909ee1412188bf89035950c2eb"
AVERITEC_REV = "2ca9dee23a2a6fa64c5bd918e0cd28ed0aa09031"

def gh(repo, revision, path):
    return f"https://raw.githubusercontent.com/{repo}/{revision}/{path}"

def hf(path, binary=False):
    kind = "resolve" if binary else "raw"
    return f"https://huggingface.co/chenxwh/AVeriTeC/{kind}/{AVERITEC_REV}/{path}"

SOURCES = {
    "asa": {
        "title": "ASA assertion-level starter pack (user-supplied, unreviewed drafts)",
        "split": "diagnostic_no_official_split", "expected_count": 30,
        "revision": "uploaded-v0.1.0-2026-09-19",
        "source_archive": "bundled/ASA_test_pack_2026-09-19.zip",
        "source_archive_sha256": "95119566d269a3194bff913fda98cb65f9a461a9e53dcf99ee0d0b871d8f3157",
        "license": "Preserve uploaded notices; no new rights over ASA or third-party material are asserted",
        "data_bundled": True,
    },
    "finqa": {
        "title": "FinQA labeled public test", "split": "test", "expected_count": 1147,
        "revision": FINQA_REV, "license": "MIT (repository); preserve third-party rights",
        "source_page": "https://github.com/czyssrs/FinQA",
        "data_url": gh("czyssrs/FinQA", FINQA_REV, "dataset/test.json"),
        "git_blob_sha1": "59958c7c3bb3b21f4dff6bc912a0fe0ae710aee0",
        "data_format": "json", "raw_name": "test.json",
        "scorer_url": gh("czyssrs/FinQA", FINQA_REV, "code/evaluate/evaluate.py"),
        "scorer_name": "finqa_official.py",
        "license_url": gh("czyssrs/FinQA", FINQA_REV, "LICENSE"),
        "readme_url": gh("czyssrs/FinQA", FINQA_REV, "README.md"),
    },
    "financebench": {
        "title": "FinanceBench 150-example public sample", "split": "public_sample",
        "expected_count": 150, "revision": FINANCE_REV,
        "license": "CC BY-NC 4.0 (dataset); original report rights are separate",
        "source_page": "https://github.com/patronus-ai/financebench",
        "license_page": "https://huggingface.co/datasets/PatronusAI/financebench",
        "data_url": gh("patronus-ai/financebench", FINANCE_REV, "data/financebench_open_source.jsonl"),
        "git_blob_sha1": "4aef1d43a443474ba193f158f2baf70550ff528d",
        "data_format": "jsonl", "raw_name": "financebench_open_source.jsonl",
        "metadata_url": gh("patronus-ai/financebench", FINANCE_REV, "data/financebench_document_information.jsonl"),
        "tree_url": f"https://api.github.com/repos/patronus-ai/financebench/git/trees/{FINANCE_REV}?recursive=1",
        "readme_url": gh("patronus-ai/financebench", FINANCE_REV, "README.md"),
    },
    "averitec": {
        "title": "AVeriTeC FEVER-7 development split (local evaluation)",
        "split": "dev", "expected_count": 500, "revision": AVERITEC_REV,
        "license": "CC BY-NC 4.0; source-document rights are separate",
        "source_page": "https://fever.ai/dataset/averitec.html",
        "data_url": hf("data/dev.json"), "data_format": "json", "raw_name": "dev.json",
        "readme_url": hf("README.md"),
        "scorer_url": hf("src/prediction/evaluate_veracity.py"),
        "scorer_name": "averitec_official.py",
        "corpus_url": hf("data_store/knowledge_store/dev_knowledge_store.zip", binary=True),
        "corpus_sha256": "021e258cd6fb5fe6d627a4667d663e95c184c966939c15124df9206142fc2212",
        "corpus_note": "Approximately 11.5 GB download; additional space needed to extract. Never deserialize pickle files.",
    },
}
LABELS = ["Supported", "Refuted", "Not Enough Evidence", "Conflicting Evidence/Cherrypicking"]
