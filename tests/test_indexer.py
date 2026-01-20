import unittest
from unittest.mock import MagicMock
from swecli.core.context_engineering.retrieval.indexer import CodebaseIndexer

class TestCodebaseIndexer(unittest.TestCase):
    def setUp(self):
        self.indexer = CodebaseIndexer()
        # Mock the token monitor to return the length of the string as token count
        # This makes it easy to reason about: "abc" is 3 tokens.
        # Note: \n\n is 2 characters, so it counts as 2 tokens in this mock.
        self.indexer.token_monitor = MagicMock()
        self.indexer.token_monitor.count_tokens.side_effect = lambda s: len(s)

    def test_compress_content_no_truncation(self):
        content = "Para1\n\nPara2\n\nPara3"
        # Length: 5 + 2 + 5 + 2 + 5 = 19
        result = self.indexer._compress_content(content, max_tokens=100)
        self.assertEqual(result, content)

    def test_compress_content_truncation(self):
        content = "Para1\n\nPara2\n\nPara3"
        # Para1 (5) + \n\n (2) + Para2 (5) = 12. Total so far: 12.
        # Next is \n\n (2) + Para3 (5). Total would be 19.
        # If max_tokens = 15, it should include Para1 and Para2.
        # Wait, the loop adds paragraph, then joins everything.
        # Iter 1: "Para1" (5) <= 15. OK.
        # Iter 2: "Para1\n\nPara2" (12) <= 15. OK.
        # Iter 3: "Para1\n\nPara2\n\nPara3" (19) > 15. Break.
        # So result should be "Para1\n\nPara2".
        result = self.indexer._compress_content(content, max_tokens=15)
        expected = "Para1\n\nPara2"
        self.assertEqual(result, expected)

    def test_compress_content_exact_boundary(self):
        content = "Para1\n\nPara2"
        # 5 + 2 + 5 = 12
        result = self.indexer._compress_content(content, max_tokens=12)
        self.assertEqual(result, content)

    def test_compress_content_large_input(self):
        # Create many paragraphs to ensure correctness
        paragraphs = [f"P{i}" for i in range(1000)]
        content = "\n\n".join(paragraphs)
        result = self.indexer._compress_content(content, max_tokens=50)
        self.assertLessEqual(len(result), 50)
        self.assertTrue(result.startswith("P0"))

if __name__ == '__main__':
    unittest.main()
