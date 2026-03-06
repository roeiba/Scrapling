"""Built-in Reddit Spider for Scrapling.

Scrapes posts and hierarchical comment trees from any subreddit.
Designed to run standalone or as a Cloud Run handler with GCS output.
"""

from scrapling.spiders.spider import Spider
from scrapling.spiders.request import Request
from scrapling.core._types import Dict, Any, Optional, List

try:
    from scrapling.fetchers import AsyncStealthySession
except ImportError:
    AsyncStealthySession = None


class RedditSpider(Spider):
    """Spider that scrapes Reddit posts and their threaded comment trees.

    Args:
        subreddit_url: Full URL to the subreddit page to scrape (e.g. https://www.reddit.com/r/AgentsOfAI/new/)
        crawldir: Optional directory for checkpoint files.
    """

    name = "reddit"

    def __init__(
        self,
        subreddit_url: str = "https://www.reddit.com/r/AgentsOfAI/new/",
        crawldir=None,
        **kwargs,
    ):
        super().__init__(crawldir=crawldir, **kwargs)
        self.subreddit_url = subreddit_url
        self.start_urls = [subreddit_url]

    def configure_sessions(self, manager):
        if AsyncStealthySession is None:
            raise ImportError(
                "AsyncStealthySession requires scrapling[fetchers]. "
                "Install with: pip install 'scrapling[fetchers]'"
            )
        manager.add(
            "stealth",
            AsyncStealthySession(headless=True, network_idle=True),
            lazy=True,
        )

    async def parse(self, response):
        """Parse the subreddit listing page and follow post links."""
        # Extract subreddit path from the URL for link matching
        # e.g. https://www.reddit.com/r/AgentsOfAI/new/ -> /r/AgentsOfAI/
        from urllib.parse import urlparse

        parsed = urlparse(self.subreddit_url)
        path_parts = parsed.path.strip("/").split("/")
        # Build the base subreddit path: /r/<subreddit_name>/
        if len(path_parts) >= 2:
            subreddit_base = f"/{path_parts[0]}/{path_parts[1]}/"
        else:
            subreddit_base = parsed.path

        post_links = response.css(
            f'a[href^="{subreddit_base}comments/"]::attr(href)'
        ).getall()
        post_links = list(set(post_links))

        for link in post_links:
            url = link if link.startswith("http") else f"https://www.reddit.com{link}"
            yield Request(url, sid="stealth", callback=self.parse_post)

    def parse_comment_tree(self, comment_el) -> Dict[str, Any]:
        """Recursively parses a shreddit-comment element and its children."""
        author = comment_el.attrib.get("author")
        score = comment_el.attrib.get("score")
        depth_val = comment_el.attrib.get("depth")
        depth = int(depth_val) if depth_val and depth_val.isdigit() else 0

        text_elements = comment_el.css(
            'div[slot="comment"] p::text, .usertext-body p::text'
        ).getall()
        text = " ".join([t.strip() for t in text_elements if t.strip()])

        comment_data: Dict[str, Any] = {
            "author": author,
            "score": score,
            "depth": depth,
            "text": text,
            "replies": [],
        }

        descendants = comment_el.css("shreddit-comment")
        for d in descendants:
            d_depth_val = d.attrib.get("depth")
            if d_depth_val and d_depth_val.isdigit() and int(d_depth_val) == depth + 1:
                comment_data["replies"].append(self.parse_comment_tree(d))

        return comment_data

    async def parse_post(self, response):
        """Parse an individual post page for content and comments."""
        title = response.css("shreddit-title::attr(title), title::text").get()

        # Extract the post body text
        content = response.css(
            'shreddit-post div[slot="text-body"] p::text'
        ).getall()
        if not content:
            content = response.css(
                '.usertext-body p::text, div[data-post-click-location="text-body"] p::text'
            ).getall()

        content_text = " ".join([c.strip() for c in content if c.strip()])

        # Post metadata from shreddit-post element attributes
        post_el = response.css("shreddit-post")
        post_score = post_el[0].attrib.get("score") if post_el else None
        post_author = post_el[0].attrib.get("author") if post_el else None

        # Build hierarchical comment tree
        comments_data: List[Dict[str, Any]] = []
        all_comments = response.css("shreddit-comment")
        for c in all_comments:
            if c.attrib.get("depth") == "0":
                comments_data.append(self.parse_comment_tree(c))

        post_id = (
            response.url.rstrip("/").split("/")[-2]
            if "comments/" in response.url
            else "unknown"
        )

        yield {
            "post_id": post_id,
            "url": response.url,
            "title": title.strip() if title else "Unknown",
            "author": post_author,
            "score": post_score,
            "content": content_text,
            "comments": comments_data,
        }
