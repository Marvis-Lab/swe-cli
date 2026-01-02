
import pytest
from unittest.mock import MagicMock, patch, ANY
from swecli.repl.processors.context_preparer import ContextPreparer

class TestContextPreparer:
    @pytest.fixture
    def session_manager(self):
        return MagicMock()

    @pytest.fixture
    def config(self):
        conf = MagicMock()
        conf.swecli_dir = "/tmp"
        return conf

    @pytest.fixture
    def file_ops(self):
        return MagicMock()

    @pytest.fixture
    def preparer(self, session_manager, config, file_ops):
        return ContextPreparer(session_manager, config, file_ops)

    def test_enhance_query_with_at_reference(self, preparer):
        query = "check @foo.py"
        enhanced = preparer.enhance_query(query)
        assert enhanced == "check foo.py"

    def test_enhance_query_with_file_content(self, preparer, file_ops):
        query = "show me test.py"
        file_ops.read_file.return_value = "print('hello')"

        enhanced = preparer.enhance_query(query)

        assert "File contents of test.py" in enhanced
        assert "print('hello')" in enhanced
        file_ops.read_file.assert_called_with("test.py")

    def test_enhance_query_no_change(self, preparer):
        query = "hello world"
        enhanced = preparer.enhance_query(query)
        assert enhanced == query

    def test_prepare_messages_no_session(self, preparer):
        preparer.session_manager.current_session = None
        agent = MagicMock()
        agent.system_prompt = "System Prompt"

        messages = preparer.prepare_messages("query", "query", agent)

        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "System Prompt"

    def test_prepare_messages_with_session_and_playbook(self, preparer, session_manager, config):
        # Setup session
        session = MagicMock()
        session_manager.current_session = session
        session.to_api_messages.return_value = [{"role": "user", "content": "query"}]

        # Setup playbook
        playbook = MagicMock()
        session.get_playbook.return_value = playbook
        playbook.as_context.return_value = "- Strategy 1"

        # Setup config
        config.playbook = MagicMock()
        config.playbook.max_strategies = 5

        agent = MagicMock()
        agent.system_prompt = "System Prompt"

        messages = preparer.prepare_messages("query", "query", agent)

        assert len(messages) == 2 # System + User
        assert messages[0]["role"] == "system"
        assert "## Learned Strategies" in messages[0]["content"]
        assert "- Strategy 1" in messages[0]["content"]

    def test_prepare_messages_enhanced_query(self, preparer, session_manager):
        session = MagicMock()
        session_manager.current_session = session
        # Mock message history
        session.to_api_messages.return_value = [
            {"role": "user", "content": "original query"}
        ]

        agent = MagicMock()
        agent.system_prompt = "System"

        messages = preparer.prepare_messages("original query", "enhanced query", agent)

        # Verify the user message was updated with enhanced query
        assert messages[1]["content"] == "enhanced query"
