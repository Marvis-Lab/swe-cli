"""SWE-bench prediction file generation utilities."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Prediction:
    """SWE-bench compatible prediction format.

    Attributes:
        instance_id: Unique identifier in format "owner__repo-issue_number"
        model_patch: Unified diff patch or None if no changes
        model_name_or_path: Model identifier (fixed as "swecli")
    """

    instance_id: str
    model_patch: str | None = None
    model_name_or_path: str = field(default="swecli")


def save_prediction(pred: Prediction, output_dir: Path) -> tuple[Path, Path | None]:
    """Save prediction in SWE-bench format + standalone patch file.

    Overwrites existing files if they exist. If the new prediction has no patch,
    removes any existing patch file for that instance.

    Args:
        pred: Prediction dataclass instance
        output_dir: Directory to save prediction files

    Returns:
        Tuple of (pred_file_path, patch_file_path or None)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    pred_file = output_dir / f"{pred.instance_id}.pred"
    patch_file_path = output_dir / f"{pred.instance_id}.patch"

    # Overwrite .pred file (JSON format for SWE-bench)
    pred_file.write_text(json.dumps(asdict(pred), indent=2))

    # Handle .patch file (raw diff for easy git apply)
    if pred.model_patch:
        patch_file_path.write_text(pred.model_patch)
        return pred_file, patch_file_path
    else:
        # Remove old patch file if new prediction has no patch
        if patch_file_path.exists():
            patch_file_path.unlink()
        return pred_file, None


def merge_predictions(predictions_dir: Path) -> Path:
    """Merge all .pred files into preds.json for SWE-bench evaluation.

    This creates a single JSON file containing all predictions,
    suitable for batch evaluation with SWE-bench's sb-cli tool.

    Args:
        predictions_dir: Directory containing .pred files

    Returns:
        Path to the merged preds.json file
    """
    preds = []
    for pred_file in sorted(predictions_dir.glob("*.pred")):
        try:
            preds.append(json.loads(pred_file.read_text()))
        except json.JSONDecodeError:
            continue  # Skip malformed files

    merged = predictions_dir / "preds.json"
    merged.write_text(json.dumps(preds, indent=2))
    return merged


def generate_instance_id(owner: str, repo: str, issue_number: int) -> str:
    """Generate SWE-bench compatible instance ID.

    Args:
        owner: Repository owner
        repo: Repository name
        issue_number: Issue number

    Returns:
        Instance ID in format "owner__repo-issue_number"
    """
    return f"{owner}__{repo}-{issue_number}"
