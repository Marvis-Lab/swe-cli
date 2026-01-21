
import pytest
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer

def test_compress_content_logic():
    """Test that content compression respects token limits and avoids O(N^2) overhead."""
    indexer = CodebaseIndexer()

    # Create paragraphs with specific lengths
    p1 = "a" * 10
    p2 = "b" * 20
    p3 = "c" * 30
    content = f"{p1}\n\n{p2}\n\n{p3}"

    # Get reference token counts
    full_tokens = indexer.token_monitor.count_tokens(content)
    p1_p2_tokens = indexer.token_monitor.count_tokens(f"{p1}\n\n{p2}")

    # Test 1: Limit exactly at p1 + p2 tokens
    compressed = indexer._compress_content(content, p1_p2_tokens)
    assert compressed == f"{p1}\n\n{p2}"

    # Test 2: Limit slightly less than p1 + p2 tokens
    # Should strictly drop the second paragraph to stay under limit
    compressed = indexer._compress_content(content, p1_p2_tokens - 1)
    assert compressed == p1

    # Test 3: Large limit accommodating all content
    compressed = indexer._compress_content(content, full_tokens + 10)
    assert compressed == content

if __name__ == "__main__":
    # Allow running directly for quick verification
    try:
        test_compress_content_logic()
        print("All tests passed!")
    except AssertionError as e:
        print(f"Test failed: {e}")
