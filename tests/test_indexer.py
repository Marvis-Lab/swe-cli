import tempfile
import shutil
import os
from pathlib import Path
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer

def test_generate_index():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create structure
        # .
        # ├── README.md
        # ├── main.py
        # ├── src/
        # │   ├── utils.py
        # ├── node_modules/ (ignored)
        # │   ├── lib.js
        # ├── .git/ (ignored)
        # │   ├── config

        (temp_path / "README.md").write_text("# Test Project\n\nThis is a test.")
        (temp_path / "main.py").write_text("print('hello')")
        (temp_path / "src").mkdir()
        (temp_path / "src" / "utils.py").write_text("def util(): pass")

        (temp_path / "node_modules").mkdir()
        (temp_path / "node_modules" / "lib.js").write_text("console.log('ignored')")

        (temp_path / ".git").mkdir()
        (temp_path / ".git" / "config").write_text("ignored")

        indexer = CodebaseIndexer(working_dir=temp_path)
        index_content = indexer.generate_index()

        print(index_content)

        assert "# " in index_content
        assert "## Overview" in index_content
        # README.md, main.py, src/utils.py = 3 files.
        # node_modules content and .git content should be ignored.
        assert "**Total Files:** 3" in index_content

        assert "## Structure" in index_content
        assert "├── main.py" in index_content
        assert "├── src" in index_content
        assert "node_modules" not in index_content

        assert "## Key Files" in index_content
        assert "main.py" in index_content
