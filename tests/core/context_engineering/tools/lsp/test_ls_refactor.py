from swecli.core.context_engineering.tools.lsp.ls import SolidLanguageServer, LSPFileBuffer, DocumentSymbols
from swecli.core.context_engineering.tools.lsp.ls_types import UnifiedSymbolInformation, SymbolKind, Location
import unittest
from unittest.mock import MagicMock, patch
import os

class ConcreteSolidLanguageServer(SolidLanguageServer):
    def _start_server(self) -> None:
        pass

class TestSolidLanguageServer(unittest.TestCase):
    def setUp(self):
        self.config = MagicMock()
        self.config.ignored_paths = []
        self.config.encoding = "utf-8"
        self.config.trace_lsp_communication = False
        self.config.start_independent_lsp_process = False

        self.repository_root = "/tmp/repo"
        self.launch_info = MagicMock()
        self.language_id = "python"
        self.settings = MagicMock()
        self.settings.project_data_relative_path = ".data"
        self.settings.get_ls_specific_settings.return_value = {}

        # Mock Language.from_ls_class
        with patch("swecli.core.context_engineering.tools.lsp.ls.Language") as MockLanguage:
            MockLanguage.from_ls_class.return_value = "python"
            self.ls = ConcreteSolidLanguageServer(
                config=self.config,
                repository_root_path=self.repository_root,
                process_launch_info=self.launch_info,
                language_id=self.language_id,
                solidlsp_settings=self.settings
            )

    def test_is_ignored_path(self):
        # Mock os.path.exists and os.path.isfile
        with patch("os.path.exists", return_value=True), \
             patch("os.path.isfile", return_value=True), \
             patch("swecli.core.context_engineering.tools.lsp.ls.match_path", return_value=False):

            self.ls.language.get_source_fn_matcher.return_value.is_relevant_filename.return_value = True

            self.assertFalse(self.ls.is_ignored_path("test.py"))

    def test_determine_log_level(self):
        self.assertEqual(SolidLanguageServer._determine_log_level("Error detected"), 40) # logging.ERROR
        self.assertEqual(SolidLanguageServer._determine_log_level("Info message"), 20) # logging.INFO

if __name__ == '__main__':
    unittest.main()
