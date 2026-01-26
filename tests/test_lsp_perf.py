import sys
import unittest
from unittest.mock import MagicMock, patch
import os

# Add repo root to sys.path
sys.path.append(os.getcwd())

from swecli.core.context_engineering.tools.lsp.ls import SolidLanguageServer
from swecli.core.context_engineering.tools.lsp.ls_config import LanguageServerConfig, Language
from swecli.core.context_engineering.tools.lsp.settings import SolidLSPSettings
from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler.server import ProcessLaunchInfo

class MockLS(SolidLanguageServer):
    def _start_server(self):
        pass

    @classmethod
    def get_language_enum_instance(cls):
        return Language.PYTHON

class TestLSPPerf(unittest.TestCase):
    def setUp(self):
        self.config = LanguageServerConfig(code_language=Language.PYTHON)
        self.settings = SolidLSPSettings()
        self.repo_root = os.getcwd()

        self.process_launch_info = ProcessLaunchInfo(cmd="echo")

        self.language_patcher = patch('swecli.core.context_engineering.tools.lsp.ls_config.Language.from_ls_class')
        self.mock_language_from_ls_class = self.language_patcher.start()
        self.mock_language_from_ls_class.return_value = Language.PYTHON

    def tearDown(self):
        self.language_patcher.stop()

    @patch('swecli.core.context_engineering.tools.lsp.ls.FileUtils')
    @patch('swecli.core.context_engineering.tools.lsp.ls.SolidLanguageServerHandler')
    def test_redundant_read_in_request_containing_symbol(self, mock_handler, mock_file_utils):
        ls = MockLS(
            config=self.config,
            repository_root_path=self.repo_root,
            process_launch_info=self.process_launch_info,
            language_id="python",
            solidlsp_settings=self.settings
        )
        ls.server_started = True

        file_path = "test_file.py"
        file_content = "def foo():\n    pass\n"
        mock_file_utils.read_file.return_value = file_content

        ls.request_document_symbols = MagicMock()
        ls.request_document_symbols.return_value = MagicMock()
        ls.request_document_symbols.return_value.iter_symbols.return_value = []

        ls.request_containing_symbol(file_path, 0)

        print(f"FileUtils.read_file called {mock_file_utils.read_file.call_count} times")

        # Expect 1 call: only in open_file
        self.assertEqual(mock_file_utils.read_file.call_count, 1)

if __name__ == '__main__':
    unittest.main()
