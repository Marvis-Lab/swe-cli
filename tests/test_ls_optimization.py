import os
import pathspec
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from swecli.core.context_engineering.tools.lsp.util.compat import match_path
from swecli.core.context_engineering.tools.lsp.ls import SolidLanguageServer

class TestLSOptimization:
    def test_match_path_with_is_dir(self):
        """Test match_path with explicit is_dir argument."""
        # Create a spec that ignores 'build/' directory
        spec = pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, ["build/"])

        # Test 1: directory 'build'
        # With is_dir=True, it should match "build/"
        assert match_path("build", spec, is_dir=True) is True

        # Test 2: file 'build' (not directory)
        # With is_dir=False, it should match "build" which does NOT match "build/"
        assert match_path("build", spec, is_dir=False) is False

        # Test 3: Legacy behavior (requires os.path.isdir, we can mock it)
        with patch("os.path.isdir", return_value=True):
             # If it thinks it's a dir, it appends / and matches
             assert match_path("build", spec, is_dir=None) is True

        with patch("os.path.isdir", return_value=False):
             # If it thinks it's a file, it doesn't match "build/"
             assert match_path("build", spec, is_dir=None) is False

    def test_is_ignored_path_optimizations(self):
        """Test SolidLanguageServer.is_ignored_path with is_file/is_dir args."""

        # Mocking SolidLanguageServer is complex due to abstract methods and __init__.
        # We'll create a dummy subclass.
        class DummyLS(SolidLanguageServer):
            def _start_server(self): pass
            def __init__(self, root):
                self.repository_root_path = root
                # ignore 'node_modules' (dir) and '*.pyc' (file)
                self._ignore_spec = pathspec.PathSpec.from_lines(
                    pathspec.patterns.GitWildMatchPattern,
                    ["node_modules/", "*.pyc"]
                )
                self.language = MagicMock()
                self.language.get_source_fn_matcher.return_value.is_relevant_filename.return_value = True

            # We need to override because the real one does complex things
            def get_ignore_spec(self):
                return self._ignore_spec

            # Mock get_language_enum_instance because __init__ calls it if we were using real __init__
            # But we overrode __init__, so maybe not needed?
            # Wait, is_ignored_path calls self.language.get_source_fn_matcher()

        ls = DummyLS("/tmp/repo")

        # Test 1: is_dir=True passed, skips exists check
        # We patch os.path.exists to raise exception if called, to prove it's NOT called
        with patch("os.path.exists", side_effect=Exception("Should not be called")):
            # node_modules is ignored
            assert ls.is_ignored_path("node_modules", is_dir=True) is True
            # src is not ignored
            assert ls.is_ignored_path("src", is_dir=True) is False

        # Test 2: is_file=True passed, skips exists check
        with patch("os.path.exists", side_effect=Exception("Should not be called")):
            # test.pyc is ignored
            assert ls.is_ignored_path("test.pyc", is_file=True) is True
            # test.py is not ignored
            assert ls.is_ignored_path("test.py", is_file=True) is False

        # Test 3: fallback behavior (no args)
        with patch("os.path.exists", return_value=True):
            with patch("os.path.isfile", return_value=True):
                 assert ls.is_ignored_path("test.pyc") is True
