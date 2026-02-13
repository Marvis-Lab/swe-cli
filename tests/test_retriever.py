import tempfile
import shutil
import os
from pathlib import Path
from swecli.core.context_engineering.retrieval.retriever import ContextRetriever

def test_resolve_file_path():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create structure
        # .
        # ├── main.py
        # ├── src/
        # │   ├── utils.py
        # ├── node_modules/ (ignored)
        # │   ├── utils.py (same name, should be ignored)

        (temp_path / "main.py").write_text("print('hello')")
        (temp_path / "src").mkdir()
        (temp_path / "src" / "utils.py").write_text("def util(): pass")

        (temp_path / "node_modules").mkdir()
        (temp_path / "node_modules" / "utils.py").write_text("ignored")

        retriever = ContextRetriever(working_dir=temp_path)

        # Test finding main.py
        path = retriever._resolve_file_path("main.py")
        assert path == temp_path / "main.py"

        # Test finding utils.py (should find src/utils.py, not node_modules/utils.py)
        # Note: os.walk order isn't guaranteed, but it should skip node_modules entirely.
        path = retriever._resolve_file_path("utils.py")
        assert path is not None
        assert "node_modules" not in str(path)
        assert path.name == "utils.py"

def test_grep_pattern_import():
    # Verify that calling _grep_pattern doesn't crash due to missing import
    # even if it returns nothing
    with tempfile.TemporaryDirectory() as temp_dir:
        retriever = ContextRetriever(working_dir=Path(temp_dir))
        # This calls subprocess, so it might fail to find anything, but shouldn't raise NameError
        try:
            retriever._grep_pattern("something")
        except NameError as e:
            assert False, f"Raised NameError: {e}"
        except Exception:
            pass # Subprocess errors are caught/swallowed
