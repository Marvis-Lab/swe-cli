"""SWE-bench dataset loader for evaluation mode."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal


def _load_dataset_safe(dataset_name: str, split: str):
    """Load dataset in a separate process to avoid Textual FD conflicts.

    The HuggingFace datasets library uses multiprocessing internally which
    conflicts with Textual's file descriptor management. We run the loading
    in a completely separate Python process with start_new_session=True.

    Args:
        dataset_name: The HuggingFace dataset name
        split: Dataset split to load (e.g., "test")

    Returns:
        The loaded dataset

    Raises:
        RuntimeError: If dataset loading fails
    """
    import os
    import pickle
    import subprocess
    import sys
    import tempfile

    def _run_in_subprocess():
        # Create a temporary file for the result
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.pkl', delete=False) as f:
            result_path = f.name

        # Python code to run in subprocess
        code = f'''
import os
import pickle
import sys

# Disable multiprocessing in HuggingFace
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_DATASETS_DISABLE_PROGRESS_BARS"] = "1"

from datasets import load_dataset

try:
    ds = load_dataset("{dataset_name}", split="{split}")
    # Convert to list of dicts for pickling
    data = [dict(row) for row in ds]
    with open("{result_path}", "wb") as f:
        pickle.dump({{"success": True, "data": data}}, f)
except Exception as e:
    with open("{result_path}", "wb") as f:
        pickle.dump({{"success": False, "error": str(e)}}, f)
'''

        # Run in completely isolated subprocess
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "close_fds": True,
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True

        result = subprocess.run(
            [sys.executable, "-c", code],
            timeout=300,
            **kwargs
        )

        # Load result from pickle file
        try:
            with open(result_path, "rb") as f:
                data = pickle.load(f)
            os.unlink(result_path)

            if not data.get("success"):
                raise RuntimeError(data.get("error", "Unknown error"))

            return data["data"]
        except FileNotFoundError:
            stderr = result.stderr.decode() if result.stderr else "No output"
            raise RuntimeError(f"Subprocess failed: {stderr}")

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_in_subprocess)
            return future.result(timeout=320)
    except Exception as e:
        raise RuntimeError(f"Failed to load dataset: {e}") from e


@dataclass
class SWEBenchInstance:
    """A single SWE-bench instance with all relevant fields.

    Attributes:
        instance_id: Unique identifier (e.g., "django__django-12345")
        repo: Repository path (e.g., "django/django")
        base_commit: Commit hash to checkout before applying fix
        problem_statement: Issue description from the dataset
        patch: Gold patch (for reference, not used in solving)
        test_patch: Test file changes from the solution PR
        fail_to_pass: Tests that should go from failing to passing
        pass_to_pass: Tests that should remain passing
    """

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch: str | None = None
    test_patch: str | None = None
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)

    @property
    def owner(self) -> str:
        """Extract repository owner from repo field."""
        return self.repo.split("/")[0]

    @property
    def repo_name(self) -> str:
        """Extract repository name from repo field."""
        return self.repo.split("/")[1]


# Dataset mapping for different SWE-bench subsets
# Keys use explicit names for clarity (swebench-lite vs just "lite")
DATASET_MAP = {
    "swebench-lite": "princeton-nlp/SWE-bench_Lite",
    "swebench-verified": "princeton-nlp/SWE-bench_Verified",
    "swebench-full": "princeton-nlp/SWE-bench",
}

DatasetType = Literal["swebench-lite", "swebench-verified", "swebench-full"]

# Valid dataset names for validation
VALID_DATASETS = tuple(DATASET_MAP.keys())


def load_swebench_instance(
    instance_id: str,
    dataset: DatasetType = "swebench-verified",
) -> SWEBenchInstance:
    """Load a single instance from SWE-bench dataset.

    Args:
        instance_id: The unique instance identifier (e.g., "django__django-12345")
        dataset: Which dataset to load from (swebench-lite, swebench-verified, swebench-full)

    Returns:
        SWEBenchInstance with all relevant fields

    Raises:
        ImportError: If the 'datasets' package is not installed
        ValueError: If the instance_id is not found in the dataset
    """
    if dataset not in DATASET_MAP:
        raise ValueError(
            f"Invalid dataset '{dataset}'. Must be one of: {list(DATASET_MAP.keys())}"
        )

    # Load the dataset (using thread pool to avoid Textual FD conflicts)
    dataset_name = DATASET_MAP[dataset]
    ds = _load_dataset_safe(dataset_name, "test")

    # Find the instance
    matches = [row for row in ds if row["instance_id"] == instance_id]

    if not matches:
        raise ValueError(
            f"Instance '{instance_id}' not found in {dataset_name}. "
            "Check the instance_id format (e.g., 'django__django-12345')"
        )

    instance = matches[0]

    # Parse JSON fields safely
    def parse_json_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []

    return SWEBenchInstance(
        instance_id=instance["instance_id"],
        repo=instance["repo"],
        base_commit=instance["base_commit"],
        problem_statement=instance["problem_statement"],
        patch=instance.get("patch"),
        test_patch=instance.get("test_patch"),
        fail_to_pass=parse_json_list(instance.get("FAIL_TO_PASS")),
        pass_to_pass=parse_json_list(instance.get("PASS_TO_PASS")),
    )


def get_all_instance_ids(dataset: DatasetType) -> list[str]:
    """Get all instance IDs from a SWE-bench dataset.

    Args:
        dataset: Which dataset to load from (swebench-lite, swebench-verified, swebench-full)

    Returns:
        List of all instance IDs in the dataset
    """
    if dataset not in DATASET_MAP:
        raise ValueError(
            f"Invalid dataset '{dataset}'. Must be one of: {', '.join(VALID_DATASETS)}"
        )

    dataset_name = DATASET_MAP[dataset]
    ds = _load_dataset_safe(dataset_name, "test")

    return [row["instance_id"] for row in ds]


def get_dataset_size(dataset: DatasetType) -> int:
    """Get the number of instances in a dataset.

    Args:
        dataset: Which dataset to check

    Returns:
        Number of instances in the dataset
    """
    if dataset not in DATASET_MAP:
        raise ValueError(
            f"Invalid dataset '{dataset}'. Must be one of: {', '.join(VALID_DATASETS)}"
        )

    dataset_name = DATASET_MAP[dataset]
    ds = _load_dataset_safe(dataset_name, "test")

    return len(ds)
