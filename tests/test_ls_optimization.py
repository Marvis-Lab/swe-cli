import os
import unittest
from unittest.mock import MagicMock, patch, Mock
import pathspec
from pathlib import Path

from swecli.core.context_engineering.tools.lsp.util.compat import match_path
from swecli.core.context_engineering.tools.lsp.ls import SolidLanguageServer

class TestLSOptimization(unittest.TestCase):
    def test_match_path_optimization(self):
        # Test that match_path respects is_dir optimization
        spec = pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, ["dir/"])

        # Without is_dir=True, "dir" should NOT match "dir/" pattern if it's not a directory
        # But here we pass is_dir=True explicitly, so it SHOULD match
        # (Assuming the logic adds trailing slash)

        self.assertTrue(match_path("dir", spec, is_dir=True))

        # Verify it doesn't call os.path.isdir when is_dir is provided
        with patch("os.path.isdir") as mock_isdir:
            match_path("dir", spec, is_dir=True)
            mock_isdir.assert_not_called()

            match_path("dir", spec, is_dir=False)
            mock_isdir.assert_not_called()

    def test_is_ignored_path_optimization(self):
        # Create a mock LS instance
        ls = MagicMock(spec=SolidLanguageServer)
        ls.repository_root_path = "/repo"
        ls.get_ignore_spec.return_value = pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, ["ignored_dir/"])
        ls.is_ignored_dirname.return_value = False

        # Attach language mock manually as spec=SolidLanguageServer doesn't run init
        ls.language = MagicMock()
        ls.language.get_source_fn_matcher.return_value.is_relevant_filename.return_value = True

        # Patch os.path.exists and os.path.isfile to verify they are skipped
        with patch("os.path.exists") as mock_exists, \
             patch("os.path.isfile") as mock_isfile:

            # Using real method bound to mock
            result = SolidLanguageServer.is_ignored_path(ls, "ignored_dir", is_dir=True, is_file=False)

            self.assertTrue(result)
            mock_exists.assert_not_called()
            mock_isfile.assert_not_called()

    @patch("os.scandir")
    @patch("os.path.exists")
    @patch("os.path.isfile")
    def test_request_full_symbol_tree_scandir(self, mock_isfile, mock_exists, mock_scandir):
        # Mock LS
        ls = MagicMock(spec=SolidLanguageServer)
        ls.repository_root_path = "/repo"

        ls.is_ignored_path.return_value = False # Don't ignore root or children

        # Setup scandir mock
        mock_entry = MagicMock()
        mock_entry.name = "file.py"
        mock_entry.path = "/repo/file.py"
        mock_entry.is_dir.return_value = False
        mock_entry.is_file.return_value = True

        # Context manager for scandir
        mock_scandir_iter = MagicMock()
        mock_scandir_iter.__enter__.return_value = mock_scandir_iter
        mock_scandir_iter.__exit__.return_value = None
        # Make it iterable
        mock_scandir_iter.__iter__.return_value = iter([mock_entry])

        mock_scandir.return_value = mock_scandir_iter

        # Mock checks for the initial path passed to request_full_symbol_tree
        mock_exists.return_value = True
        mock_isfile.return_value = False # It is a directory

        # We need to mock _open_file_context context manager
        ls._open_file_context.return_value.__enter__.return_value.contents = "content"
        ls._open_file_context.return_value.__exit__.return_value = None
        ls.request_document_symbols.return_value.root_symbols = []

        # Helper for _get_range_from_file_content
        ls._get_range_from_file_content.return_value = {"start": 0, "end": 0}

        # Run method
        SolidLanguageServer.request_full_symbol_tree(ls, ".")

        # Verify scandir called
        mock_scandir.assert_called_with(os.path.realpath("/repo"))

        # Verify is_ignored_path was called with optimization flags for the child
        # Check calls
        found_call = False
        for call in ls.is_ignored_path.call_args_list:
            args, kwargs = call
            if args[0] == "file.py":
                self.assertEqual(kwargs.get("is_dir"), False)
                self.assertEqual(kwargs.get("is_file"), True)
                found_call = True
                break

        self.assertTrue(found_call, "Did not find is_ignored_path call for file.py with correct flags")

if __name__ == '__main__':
    unittest.main()
