"""ClimateBERT environmental_claims: sentence-level claim identification. CC BY-NC-SA 4.0."""
from datasets.adapters.base import Example, read_rows


def load(path):
    for i, row in enumerate(read_rows(path)):
        yield Example(id=f"envclaims-{i}", dataset="environmental_claims",
                      model_visible={"text": row["text"]},
                      evaluation_only={"label": int(row["label"])})
