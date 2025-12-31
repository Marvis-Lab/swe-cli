
import unittest
from unittest.mock import MagicMock, patch
from swecli.repl.query_processor import QueryProcessor

class TestQueryProcessor(unittest.TestCase):
    def setUp(self):
        self.console = MagicMock()
        self.session_manager = MagicMock()
        self.config = MagicMock()
        self.config_manager = MagicMock()
        self.mode_manager = MagicMock()
        self.file_ops = MagicMock()
        self.output_formatter = MagicMock()
        self.status_line = MagicMock()
        self.message_printer_callback = MagicMock()

        self.processor = QueryProcessor(
            console=self.console,
            session_manager=self.session_manager,
            config=self.config,
            config_manager=self.config_manager,
            mode_manager=self.mode_manager,
            file_ops=self.file_ops,
            output_formatter=self.output_formatter,
            status_line=self.status_line,
            message_printer_callback=self.message_printer_callback
        )

    def test_init(self):
        self.assertIsNotNone(self.processor)

    def test_enhance_query_no_change(self):
        query = "hello world"
        enhanced = self.processor.enhance_query(query)
        self.assertEqual(enhanced, query)

    def test_enhance_query_with_file_ref(self):
        query = "look at @test.py"
        enhanced = self.processor.enhance_query(query)
        self.assertEqual(enhanced, "look at test.py")

    def test_enhance_query_with_content(self):
        query = "explain test.py"
        self.file_ops.read_file.return_value = "print('hello')"
        enhanced = self.processor.enhance_query(query)
        self.assertIn("File contents of test.py", enhanced)
        self.assertIn("print('hello')", enhanced)

    def test_prepare_messages_no_session(self):
        self.session_manager.current_session = None
        agent = MagicMock()
        agent.system_prompt = "system prompt"
        messages = self.processor._prepare_messages("query", "enhanced query", agent)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "system prompt")

    def test_prepare_messages_with_session(self):
        session = MagicMock()
        self.session_manager.current_session = session
        session.to_api_messages.return_value = [{"role": "user", "content": "query"}]
        session.get_playbook.return_value = MagicMock()

        agent = MagicMock()
        agent.system_prompt = "system prompt"

        # Mock playbook config
        self.config.playbook = MagicMock()
        self.config.playbook.max_strategies = 10
        self.config.playbook.use_selection = True
        self.config.playbook.scoring_weights.to_dict.return_value = {}
        self.config.playbook.embedding_model = "test-model"
        self.config.playbook.cache_file = None
        self.config.playbook.cache_embeddings = False
        self.config.swecli_dir = "/tmp"

        messages = self.processor._prepare_messages("query", "enhanced query", agent)
        # Should have system prompt prepended
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "enhanced query")

if __name__ == '__main__':
    unittest.main()
