import shutil
import tempfile
import time
from pathlib import Path
import pytest
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer

class TestCodebaseIndexer:
    @pytest.fixture
    def repo_path(self):
        # Create temp dir
        path = Path(tempfile.mkdtemp())
        yield path
        # Cleanup
        if path.exists():
            shutil.rmtree(path)

    def test_performance_and_ignore(self, repo_path):
        root = repo_path

        # Create some key files
        (root / "main.py").touch()
        (root / "README.md").touch()

        # Create node_modules with files
        node_modules = root / "node_modules"
        node_modules.mkdir(exist_ok=True)

        # Create enough files to be noticeable
        for i in range(5):
            pkg = node_modules / f"pkg_{i}"
            pkg.mkdir(exist_ok=True)
            for j in range(5):
                (pkg / f"file_{j}.js").touch()

        # Create ignored file that matches pattern if not ignored
        # key_patterns has "Tests": ["test_*.py", ...]
        (node_modules / "test_ignored.py").touch()

        # Normal source
        src = root / "src"
        src.mkdir(exist_ok=True)
        (src / "app.py").touch()

        indexer = CodebaseIndexer(working_dir=repo_path)

        output = indexer._generate_key_files()

        assert "main.py" in output
        assert "README.md" in output
        # app.py is in Main pattern ["app.py"]
        assert "src/app.py" in output

        # Should NOT contain node_modules files
        assert "node_modules" not in output
        assert "test_ignored.py" not in output
