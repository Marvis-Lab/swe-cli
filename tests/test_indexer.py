
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer

class TestCodebaseIndexer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.working_dir = Path(self.test_dir)

        # Create some dummy files
        (self.working_dir / "main.py").touch()
        (self.working_dir / "utils.py").touch()
        (self.working_dir / "README.md").write_text("This is a test project.\n\nDescription here.")
        (self.working_dir / "requirements.txt").write_text("numpy\npandas")

        # Create nested structure
        (self.working_dir / "src").mkdir()
        (self.working_dir / "src" / "core.py").touch()

        # Create ignored directories
        (self.working_dir / "node_modules").mkdir()
        (self.working_dir / "node_modules" / "pkg").mkdir()
        (self.working_dir / "node_modules" / "pkg" / "index.js").touch()

        self.indexer = CodebaseIndexer(working_dir=self.working_dir)
        # Pre-populate data by walking
        self.indexer._walk_and_collect()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_generate_overview(self):
        overview = self.indexer._generate_overview()
        self.assertIn("Total Files:", overview)
        # Check that it counted correctly: main.py, utils.py, README.md, requirements.txt, src/core.py = 5 files
        self.assertIn("5", overview)

    def test_generate_structure(self):
        structure = self.indexer._generate_structure()
        self.assertIn("src/", structure)
        self.assertIn("core.py", structure)
        # Should NOT include node_modules
        self.assertNotIn("node_modules", structure)

    def test_generate_key_files(self):
        key_files = self.indexer._generate_key_files()
        self.assertIn("main.py", key_files)
        self.assertIn("README.md", key_files)
        self.assertIn("requirements.txt", key_files)

    def test_generate_index(self):
        # generate_index will call _walk_and_collect again, which is fine
        index = self.indexer.generate_index()
        self.assertIn("# ", index)
        self.assertIn("## Overview", index)
        self.assertIn("## Structure", index)
        self.assertIn("## Key Files", index)
        self.assertIn("## Dependencies", index)
