import os
import time
from pathlib import Path
import tempfile
from swecli.core.context_engineering.retrieval.retriever import ContextRetriever
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer

def test_retriever_subprocess_import():
    print("Testing ContextRetriever subprocess import fix...")
    # Create a dummy file to find
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / "test_file.py").touch()
        (tmp_path / "test_file.py").write_text("def my_func(): pass")

        retriever = ContextRetriever(working_dir=tmp_path)
        # calling _grep_pattern which uses subprocess
        # Pass a pattern that likely won't be found by rg if not installed,
        # but we want to exercise the code path.
        # If rg is installed, it runs rg. If not, it runs grep.
        # Both use subprocess.

        try:
            retriever._grep_pattern("my_func")
            print("ContextRetriever._grep_pattern executed successfully (no NameError).")
        except NameError as e:
            print(f"FAILED: NameError detected: {e}")
            exit(1)
        except Exception as e:
            print(f"ContextRetriever._grep_pattern raised {type(e).__name__}: {e}")
            # This might be okay if it's not NameError, but ideally it shouldn't raise.

def test_indexer_performance():
    print("Testing CodebaseIndexer performance...")
    # We can't easily generate a huge codebase here, but we can verify logic correctness
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").touch()

        # Create ignored dir
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "huge_file.js").touch()

        indexer = CodebaseIndexer(working_dir=tmp_path)

        start_time = time.time()
        files = indexer._find_files(["*.py"])
        end_time = time.time()

        print(f"Found files: {[f.name for f in files]}")

        # Should find main.py and test_main.py
        found_names = {f.name for f in files}
        assert "main.py" in found_names
        assert "test_main.py" in found_names

        # Should NOT find anything in node_modules if we searched for js
        js_files = indexer._find_files(["*.js"])
        print(f"Found JS files: {[f.name for f in js_files]}")
        assert "huge_file.js" not in [f.name for f in js_files], "Should exclude node_modules"

        print(f"Indexer traversal took {end_time - start_time:.4f}s")

        # Test compress content
        content = "\n\n".join(["paragraph " + str(i) for i in range(100)])
        start_time = time.time()
        compressed = indexer._compress_content(content, max_tokens=100) # strict limit
        end_time = time.time()
        print(f"Compress content took {end_time - start_time:.4f}s")
        assert len(compressed) < len(content)

if __name__ == "__main__":
    test_retriever_subprocess_import()
    test_indexer_performance()
