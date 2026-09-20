"""QuanTemp: real-world numerical and temporal claims. License: unverified."""
import json
import re
import zipfile
from pathlib import Path

from datasets.adapters.base import Example, gold, read_rows

# The fact-check article and its URL state the verdict, so they are kept with the gold fields.
GOLD = ("label", "label_original", "doc", "url")

# The publisher's retrieved web snippets for each test claim, best match first.
EVIDENCE = "bm25_top_100_claimdecomp.json.zip"
SNIPPETS_PER_CLAIM = 30
# A snippet that names a fact-checker or states a rating can give the verdict away, so it is not
# given to a system under test. A snippet that states a verdict in other words is not caught.
LEAK = re.compile(r"fact[\s-]?check|politifact|snopes|full\s?fact|africa\s?check|pants on fire|"
                  r"pinocchio|\brat(?:ed|ing)\b.{0,15}\b(?:true|false|misleading)|"
                  r"\b(?:mostly|half|partly)[\s-](?:true|false)\b|\bdebunk", re.I)


def _snippets(source: Path) -> dict[str, list[str]]:
    """Claim text to its retrieved snippets, when the evidence file is beside the claims file."""
    path = source.parent / EVIDENCE
    if not path.exists():
        return {}
    with zipfile.ZipFile(path) as archive, archive.open(EVIDENCE.removesuffix(".zip")) as handle:
        return {record["claim"].strip(): record["docs"] for record in json.load(handle)}


def load(path):
    snippets = _snippets(Path(path))
    # The published files are named train_, val_, and test_claims_quantemp.json. The split goes
    # into the id, because row numbers start at 0 in each of them.
    split = Path(path).stem.removesuffix("_claims_quantemp")
    prefix = f"quantemp-{split}" if split != Path(path).stem else "quantemp"
    for i, row in enumerate(read_rows(path)):
        fields = {k: row.get(k) for k in GOLD}
        # Some taxonomy values carry trailing spaces in the published file.
        fields["taxonomy_label"] = (row.get("taxonomy_label") or "").strip() or None
        kept = [s for s in snippets.get(row["claim"].strip(), []) if s.strip() and not LEAK.search(s)]
        yield Example(
            id=f"{prefix}-{i}", dataset="quantemp",
            model_visible={"claim": row["claim"], "country_of_origin": row.get("country_of_origin"),
                           "lang": row.get("lang")},
            evaluation_only=gold("quantemp", i, fields, ("label",)),
            # Only the test split has retrieved snippets. The other splits have no documents.
            searchable=[{"content": s, "media_type": "text/plain"} for s in kept[:SNIPPETS_PER_CLAIM]])
