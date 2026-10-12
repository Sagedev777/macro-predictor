import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock, patch

import sentiment


class SentimentSourceTests(unittest.TestCase):
    def test_rss_parser_keeps_recent_keyword_matches_and_skips_old_entries(self):
        now = datetime.now(timezone.utc)
        recent_date = format_datetime(now)
        old_date = format_datetime(now - timedelta(days=3))
        response = Mock()
        response.content = (
            "<rss><channel>"
            f"<item><title>Dollar gains</title><description>Strong growth</description>"
            f"<pubDate>{recent_date}</pubDate></item>"
            f"<item><title>Federal Reserve</title><description>Old policy story</description>"
            f"<pubDate>{old_date}</pubDate></item>"
            "</channel></rss>"
        ).encode("utf-8")

        with patch(
            "config.events.RSS_FEEDS", {"USD": ["https://example.test/feed.xml"]}
        ), patch.object(sentiment.requests, "get", return_value=response):
            articles = sentiment._fetch_rss_articles("USD", hours=48)

        response.raise_for_status.assert_called_once_with()
        self.assertEqual(articles, ["Dollar gains Strong growth"])


if __name__ == "__main__":
    unittest.main()
