"""AVeriTeC: real-world claims with question-answer evidence. CC BY-NC 4.0."""
from datasets.adapters.base import Example, gold, read_rows

VISIBLE = ("claim", "claim_date", "speaker", "reporting_source", "location_ISO_code")
# The fact-checking article states the verdict, so it is kept with the gold fields.
GOLD = ("label", "justification", "questions", "fact_checking_article")


def load(path):
    for i, row in enumerate(read_rows(path)):
        yield Example(id=f"averitec-{i}", dataset="averitec",
                      model_visible={k: row.get(k) for k in VISIBLE},
                      evaluation_only=gold("averitec", i, {k: row.get(k) for k in GOLD},
                                           ("label",)))
