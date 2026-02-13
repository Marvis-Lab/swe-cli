
import pytest
from pathlib import Path
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer

def test_generate_index(tmp_path):
    """Test basic index generation."""
    # Create fake project structure
    (tmp_path / "README.md").write_text("# Test Project\n\nThis is a test.")
    (tmp_path / "requirements.txt").write_text("flask==2.0.0\nrequests==2.28.0\n")
    (tmp_path / "main.py").write_text("def main():\n    pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    pass\n")

    indexer = CodebaseIndexer(working_dir=tmp_path)
    content = indexer.generate_index()

    assert len(content) > 0, "Should generate content"
    assert "# " in content, "Should have title"
    assert "## Overview" in content, "Should have overview"
    assert "# Test Project" in content

def test_key_files_detection(tmp_path):
    """Test key files detection."""
    # Create key files
    (tmp_path / "main.py").write_text("# Main")
    (tmp_path / "setup.py").write_text("# Setup")
    (tmp_path / "requirements.txt").write_text("flask")
    (tmp_path / "README.md").write_text("# README")

    # Nested file
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "app.py").write_text("# App")

    indexer = CodebaseIndexer(working_dir=tmp_path)
    content = indexer.generate_index()

    # Should detect these key files
    assert "Key Files" in content, "Should have key files section"
    assert "main.py" in content
    assert "setup.py" in content
    assert "requirements.txt" in content
    # app.py matches app.py pattern (in Main)
    assert "src/app.py" in content

def test_scan_key_files_logic(tmp_path):
    """Directly test _scan_key_files logic."""
    indexer = CodebaseIndexer(working_dir=tmp_path)

    # Create structure
    (tmp_path / "main.py").touch()
    (tmp_path / "test_foo.py").touch()
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "app.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_bar.py").touch()

    key_patterns = {
        "Main": ["main.py", "app.py"],
        "Tests": ["test_*.py", "tests/"]
    }

    results = indexer._scan_key_files(key_patterns)

    main_files = [p.name for p in results["Main"]]
    assert "main.py" in main_files
    assert "app.py" in main_files

    test_files = [p.name for p in results["Tests"]]
    assert "test_foo.py" in test_files
    assert "tests" in test_files # Directory match
