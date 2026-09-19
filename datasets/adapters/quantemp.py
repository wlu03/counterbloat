"""QuanTemp: real-world numerical and temporal claims. License: unverified."""
from datasets.adapters.base import Example, gold, read_rows

# The fact-check article and its URL state the verdict, so they are kept with the gold fields.
GOLD = ("label", "label_original", "doc", "url")


def load(path):
    for i, row in enumerate(read_rows(path)):
        fields = {k: row.get(k) for k in GOLD}
        # Some taxonomy values carry trailing spaces in the published file.
        fields["taxonomy_label"] = (row.get("taxonomy_label") or "").strip() or None
        yield Example(
            id=f"quantemp-{i}", dataset="quantemp",
            model_visible={"claim": row["claim"], "country_of_origin": row.get("country_of_origin"),
                           "lang": row.get("lang")},
            evaluation_only=gold("quantemp", i, fields, ("label",)))
