import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from swecli.core.context_engineering.tools.lsp.ls import SolidLanguageServer
from swecli.core.context_engineering.tools.lsp.ls_config import LanguageServerConfig, Language
from swecli.core.context_engineering.tools.lsp.settings import SolidLSPSettings

class MockLanguageServer(SolidLanguageServer):
    def _start_server(self):
        pass

    def is_ignored_dirname(self, dirname: str) -> bool:
        return False

    @classmethod
    def get_language_enum_instance(cls):
        return Language.PYTHON

class TestLSPPerf(unittest.TestCase):
    def setUp(self):
        self.config = MagicMock(spec=LanguageServerConfig)
        self.config.encoding = "utf-8"
        self.config.code_language = Language.PYTHON
        self.config.trace_lsp_communication = False
        self.config.start_independent_lsp_process = False
        self.config.ignored_paths = []

        self.settings = MagicMock(spec=SolidLSPSettings)
        self.settings.project_data_relative_path = ".swecli"
        self.settings.ls_resources_dir = "/tmp/ls_resources"

        # Patch dependencies to avoid side effects
        with patch('swecli.core.context_engineering.tools.lsp.ls.SolidLanguageServerHandler') as MockHandler, \
             patch('pathlib.Path.mkdir'), \
             patch('swecli.core.context_engineering.tools.lsp.ls.SolidLanguageServer._load_raw_document_symbols_cache'), \
             patch('swecli.core.context_engineering.tools.lsp.ls.SolidLanguageServer._load_document_symbols_cache'):

            self.ls = MockLanguageServer(
                config=self.config,
                repository_root_path="/tmp/repo",
                process_launch_info=MagicMock(),
                language_id="python",
                solidlsp_settings=self.settings
            )
            self.ls.server_started = True

    @patch('swecli.core.context_engineering.tools.lsp.ls.FileUtils.read_file')
    def test_request_containing_symbol_reads(self, mock_read_file):
        # Setup mock file content
        mock_read_file.return_value = "def foo():\n    pass\n"

        # Mock server response for document symbols
        self.ls.server.send.document_symbol.return_value = []

        # Call request_containing_symbol
        self.ls.request_containing_symbol("test.py", 0, 0)

        print(f"read_file call count: {mock_read_file.call_count}")

        # Verify call count.
        # After fix, we expect exactly 1 call (initial open).
        self.assertEqual(mock_read_file.call_count, 1, "Should be efficient after fix")

if __name__ == '__main__':
    unittest.main()
