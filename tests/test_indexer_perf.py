import pytest
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer
from swecli.core.context_engineering.retrieval.token_monitor import ContextTokenMonitor

class TestCodebaseIndexerPerf:
    def test_compress_content_truncation(self):
        """Test that _compress_content correctly truncates content."""
        indexer = CodebaseIndexer()

        # Create a large content with many paragraphs
        # Each paragraph is roughly "Para X"
        paragraphs = [f"This is paragraph number {i} with some content." for i in range(100)]
        content = "\n\n".join(paragraphs)

        # Calculate tokens for the full content to know what to expect
        full_tokens = indexer.token_monitor.count_tokens(content)

        # Set a limit that cuts it roughly in half
        limit = full_tokens // 2

        compressed = indexer._compress_content(content, limit)
        compressed_tokens = indexer.token_monitor.count_tokens(compressed)

        assert compressed_tokens <= limit
        assert compressed_tokens > 0
        assert len(compressed) < len(content)
        assert compressed.startswith(paragraphs[0])

    def test_compress_content_no_truncation_needed(self):
        """Test that _compress_content returns full content if within limit."""
        indexer = CodebaseIndexer()
        content = "Small content.\n\nOnly two paragraphs."
        limit = 1000 # Large limit

        compressed = indexer._compress_content(content, limit)

        assert compressed == content
