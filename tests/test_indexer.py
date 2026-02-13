
import pytest
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer

class MockTokenMonitor:
    def count_tokens(self, text: str) -> int:
        # Simple mock: 1 token per character
        return len(text)

@pytest.fixture
def indexer():
    idx = CodebaseIndexer()
    idx.token_monitor = MockTokenMonitor()
    return idx

def test_compress_content_under_limit(indexer):
    content = "para1\n\npara2"
    # Length: 5 + 2 + 5 = 12
    compressed = indexer._compress_content(content, max_tokens=20)
    assert compressed == content

def test_compress_content_over_limit(indexer):
    content = "para1\n\npara2\n\npara3"
    # Lengths: para1=5, \n\n=2, para2=5, \n\n=2, para3=5
    # Total = 19

    # Limit 10: should fit para1 (5) + \n\n (2) + para2 (5) = 12? No.
    # Accumulation:
    # 1. para1 (5). Total 5. <= 10. Added.
    # 2. para2 (5). Cost: 5 + 2 (separator) = 7. Total 5+7=12. > 10. Break.

    compressed = indexer._compress_content(content, max_tokens=10)
    assert compressed == "para1"

def test_compress_content_exact_limit(indexer):
    content = "para1\n\npara2"
    # para1 (5)
    # para2 (5) + sep (2) = 7
    # Total = 12

    compressed = indexer._compress_content(content, max_tokens=12)
    assert compressed == "para1\n\npara2"

def test_compress_content_empty(indexer):
    content = ""
    compressed = indexer._compress_content(content, max_tokens=10)
    assert compressed == ""

def test_compress_content_single_paragraph_exceeds(indexer):
    content = "verylongparagraph" # 17 chars
    compressed = indexer._compress_content(content, max_tokens=10)
    # First paragraph 17 > 10. Should break immediately?
    # Loop: p_tokens=17. cost=17. current=0. 0+17 > 10. Break.
    # Result empty list -> ""
    assert compressed == ""
