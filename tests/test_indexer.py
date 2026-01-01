
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer

@pytest.fixture
def temp_codebase():
    """Create a temporary codebase structure."""
    temp_dir = tempfile.mkdtemp()
    base = Path(temp_dir)

    # Create standard files
    (base / "README.md").write_text("Description of the project.")
    (base / "main.py").touch()
    (base / "requirements.txt").touch()

    # Create nested files
    (base / "src").mkdir()
    (base / "src" / "utils.py").touch()

    # Create ignored directories
    (base / "node_modules").mkdir()
    (base / "node_modules" / "ignored.js").touch()

    (base / ".git").mkdir()
    (base / ".git" / "HEAD").touch()

    yield base

    shutil.rmtree(temp_dir)

def test_get_all_files_ignores_dirs(temp_codebase):
    indexer = CodebaseIndexer(working_dir=temp_codebase)
    all_files = indexer._get_all_files()

    filenames = [f.name for f in all_files]

    assert "main.py" in filenames
    assert "utils.py" in filenames
    assert "README.md" in filenames
    assert "ignored.js" not in filenames
    assert "HEAD" not in filenames

def test_find_files_patterns(temp_codebase):
    indexer = CodebaseIndexer(working_dir=temp_codebase)

    # Test file extension pattern
    py_files = indexer._find_files(["*.py"])
    assert len(py_files) == 2
    assert any(f.name == "main.py" for f in py_files)
    assert any(f.name == "utils.py" for f in py_files)

    # Test specific file
    readme = indexer._find_files(["README.md"])
    assert len(readme) == 1
    assert readme[0].name == "README.md"

    # Test nested pattern
    utils = indexer._find_files(["src/utils.py"]) # glob matches src/utils.py via **/src/utils.py?
    # Our implementation uses **/{pattern}.
    # If pattern is "src/utils.py", glob is "**/src/utils.py".
    # Path(".../src/utils.py").match("**/src/utils.py") is True.
    assert len(utils) == 1
    assert utils[0].name == "utils.py"

def test_generate_overview(temp_codebase):
    indexer = CodebaseIndexer(working_dir=temp_codebase)

    # Mock token monitor to avoid Tiktoken dependency issues in test environment if not set up
    indexer.token_monitor = MagicMock()
    indexer.token_monitor.count_tokens.return_value = 100

    overview = indexer._generate_overview()

    # Total files: 3 regular files (README, main, reqs) + 1 nested (src/utils) = 4 files.
    # node_modules and .git are ignored.
    assert "**Total Files:** 4" in overview

    # Description extraction check
    assert "Description of the project." in overview
