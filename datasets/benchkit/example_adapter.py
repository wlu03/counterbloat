"""Replace this adapter with your actual Counterbloat or model call.

The supplied adapter deliberately abstains. It is not a model and produces no
benchmark performance claims. `runtime_dir` contains no bundled gold annotations.
Example: python -m datasets.benchmark run --adapter datasets.benchkit.example_adapter:predict --output abstentions.jsonl
"""
from pathlib import Path

def predict(example: dict, runtime_dir: Path) -> dict:
    # Native tasks differ. Route financial QA to a question-answering path, not to
    # document claim extraction. Route AVeriTeC's claim to the verification path.
    # Load original evidence from runtime_dir / 'corpus' as appropriate.
    # Replace this return value with a genuine inference result; never read gold files.
    return {
        'status': 'abstained',
        'reason': 'No model adapter has been connected.',
    }
