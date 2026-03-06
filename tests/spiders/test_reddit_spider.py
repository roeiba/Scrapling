"""Tests for the RedditSpider class."""

import pytest

from scrapling.spiders.reddit_spider import RedditSpider
from scrapling.spiders.request import Request


class TestRedditSpiderInit:
    """Test RedditSpider initialization."""

    def test_default_subreddit_url(self):
        """Test that spider has a default subreddit URL."""
        spider = RedditSpider()

        assert spider.subreddit_url == "https://www.reddit.com/r/AgentsOfAI/new/"
        assert spider.start_urls == ["https://www.reddit.com/r/AgentsOfAI/new/"]

    def test_custom_subreddit_url(self):
        """Test spider with custom subreddit URL."""
        url = "https://www.reddit.com/r/Python/new/"
        spider = RedditSpider(subreddit_url=url)

        assert spider.subreddit_url == url
        assert spider.start_urls == [url]

    def test_spider_name(self):
        """Test that spider has the correct name."""
        spider = RedditSpider()
        assert spider.name == "reddit"

    def test_spider_repr(self):
        """Test spider string representation."""
        spider = RedditSpider()
        assert "RedditSpider" in repr(spider)
        assert "reddit" in repr(spider)


class TestRedditSpiderSessionConfig:
    """Test RedditSpider session configuration."""

    def test_configure_sessions_adds_stealth(self):
        """Test that configure_sessions adds a stealth session."""
        spider = RedditSpider()
        assert len(spider._session_manager) > 0

    def test_stealth_session_is_named(self):
        """Test that the stealth session is registered with 'stealth' name."""
        spider = RedditSpider()
        # The session manager should have a session named 'stealth'
        assert spider._session_manager.get("stealth") is not None


class TestRedditSpiderCommentParsing:
    """Test the comment tree parsing logic."""

    def test_parse_comment_tree_basic(self):
        """Test parsing a simple comment element with mock attributes."""

        class MockElement:
            """Mock element for testing comment parsing."""

            def __init__(self, author, score, depth, text_elements=None, children=None):
                self._attribs = {
                    "author": author,
                    "score": score,
                    "depth": str(depth),
                }
                self._text = text_elements or []
                self._children = children or []

            @property
            def attrib(self):
                return self._attribs

            def css(self, selector):
                if "shreddit-comment" in selector:
                    return MockCssList(self._children)
                return MockCssList(self._text)

        class MockCssList:
            """Mock CSS selector result."""

            def __init__(self, items):
                self._items = items

            def getall(self):
                return self._items

            def __iter__(self):
                return iter(self._items)

        spider = RedditSpider()

        # Create a simple top-level comment
        comment = MockElement(
            author="test_user",
            score="42",
            depth=0,
            text_elements=["Hello ", "world"],
        )

        result = spider.parse_comment_tree(comment)

        assert result["author"] == "test_user"
        assert result["score"] == "42"
        assert result["depth"] == 0
        assert result["text"] == "Hello world"
        assert result["replies"] == []

    def test_parse_comment_tree_missing_depth(self):
        """Test parsing comment with missing depth defaults to 0."""

        class MockElement:
            def __init__(self):
                self._attribs = {"author": "user", "score": "1"}

            @property
            def attrib(self):
                return self._attribs

            def css(self, selector):
                class Empty:
                    def getall(self):
                        return []
                    def __iter__(self):
                        return iter([])
                return Empty()

        spider = RedditSpider()
        result = spider.parse_comment_tree(MockElement())
        assert result["depth"] == 0

    def test_parse_comment_tree_empty_text(self):
        """Test parsing comment with no text content."""

        class MockElement:
            @property
            def attrib(self):
                return {"author": "user", "score": "5", "depth": "1"}

            def css(self, selector):
                class Empty:
                    def getall(self):
                        return []
                    def __iter__(self):
                        return iter([])
                return Empty()

        spider = RedditSpider()
        result = spider.parse_comment_tree(MockElement())
        assert result["text"] == ""
        assert result["author"] == "user"
        assert result["depth"] == 1


class TestRedditSpiderStartRequests:
    """Test start_requests generation."""

    @pytest.mark.asyncio
    async def test_start_requests_yields_from_subreddit_url(self):
        """Test that start_requests yields a request for the subreddit URL."""
        url = "https://www.reddit.com/r/Python/new/"
        spider = RedditSpider(subreddit_url=url)
        requests = [r async for r in spider.start_requests()]

        assert len(requests) == 1
        assert requests[0].url == url

    @pytest.mark.asyncio
    async def test_start_requests_uses_default_session(self):
        """Test that start_requests uses the default session."""
        spider = RedditSpider()
        requests = [r async for r in spider.start_requests()]

        default_sid = spider._session_manager.default_session_id
        assert requests[0].sid == default_sid


class TestRedditSpiderExport:
    """Test that RedditSpider is properly exported from the package."""

    def test_importable_from_spiders(self):
        """Test that RedditSpider can be imported from scrapling.spiders."""
        from scrapling.spiders import RedditSpider as Imported
        assert Imported is RedditSpider

    def test_in_all(self):
        """Test that RedditSpider is in __all__."""
        from scrapling.spiders import __all__
        assert "RedditSpider" in __all__


class TestRedditSpiderUrlParsing:
    """Test subreddit URL parsing logic used in the parse method."""

    def test_subreddit_base_extraction(self):
        """Test that the subreddit base path is correctly extracted."""
        from urllib.parse import urlparse

        test_cases = [
            ("https://www.reddit.com/r/AgentsOfAI/new/", "/r/AgentsOfAI/"),
            ("https://www.reddit.com/r/Python/top/", "/r/Python/"),
            ("https://www.reddit.com/r/programming/", "/r/programming/"),
        ]

        for url, expected_base in test_cases:
            parsed = urlparse(url)
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 2:
                subreddit_base = f"/{path_parts[0]}/{path_parts[1]}/"
            else:
                subreddit_base = parsed.path

            assert subreddit_base == expected_base, f"Failed for {url}"
