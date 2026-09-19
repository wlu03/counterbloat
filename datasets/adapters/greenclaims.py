"""GreenClaims CSV. Accusations and case types are annotations, not adjudicated labels."""
from datasets.adapters.base import Example, read_rows


def load(path):
    for i, row in enumerate(read_rows(path)):
        yield Example(
            id=f"greenclaims-{i}", dataset="greenclaims",
            model_visible={"company": row.get("Company"), "year": row.get("Year"),
                           "url": row.get("Url"), "claim": row.get("Claim")},
            evaluation_only={"accusation": row.get("Accusation"), "type": row.get("Type")})
