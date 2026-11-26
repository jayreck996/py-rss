import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import run_daily


class FeedOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.urls = {
            "ANTHROPIC": "https://claude.com/resources/articles/test-article",
            "OPENAI": "https://openai.com/blog/test-openai",
            "COINBASE": "https://www.coinbase.com/blog/test-coinbase",
        }
        for source, url in self.urls.items():
            data_dir = self.root / "data" / source / "2026-11-22"
            data_dir.mkdir(parents=True)
            (data_dir / "article.json").write_text(
                json.dumps({
                    "url": url,
                    "source": source.lower(),
                    "title": f"{source} Test",
                    "body_text": "<p>Body</p>",
                    "published_at": "2026-11-22T00:00:00Z",
                }),
                encoding="utf-8",
            )

    def _write_source_feed(self, source: str) -> Path:
        articles = run_daily._load_articles(self.root / "data" / source)
        rss, channel, _ = run_daily._build_rss("T", "http://x", "D", "http://x/feed.xml")
        run_daily._add_items(channel, articles)
        feed_path = self.root / "XML" / source / "XML-2026Q4.xml"
        feed_path.parent.mkdir(parents=True, exist_ok=True)
        run_daily._write_feed(rss, feed_path)
        return feed_path

    def test_per_source_feed_written(self):
        feed_path = self._write_source_feed("ANTHROPIC")
        tree = ET.parse(feed_path)
        self.assertEqual(tree.findtext("./channel/item/guid"), self.urls["ANTHROPIC"])

    def test_all_three_sources_produce_feeds(self):
        for source in ("ANTHROPIC", "OPENAI", "COINBASE"):
            feed_path = self._write_source_feed(source)
            tree = ET.parse(feed_path)
            self.assertEqual(tree.findtext("./channel/item/guid"), self.urls[source])

    def test_source_failure_does_not_affect_others(self):
        feed_path = self._write_source_feed("OPENAI")
        tree = ET.parse(feed_path)
        items = tree.findall("./channel/item")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].findtext("guid"), self.urls["OPENAI"])

    def test_invalid_version_raises(self):
        with self.assertRaises(ValueError):
            import asyncio
            asyncio.run(run_daily.main(test_version=0))

    def test_missing_body_skipped(self):
        bad_dir = self.root / "data" / "ANTHROPIC" / "2026-11-22"
        (bad_dir / "article.json").write_text(
            json.dumps({"url": self.urls["ANTHROPIC"], "body_text": "plain text"}),
            encoding="utf-8",
        )
        articles = run_daily._load_articles(self.root / "data" / "ANTHROPIC")
        self.assertEqual(articles, [])

    def test_feed_path_comes_from_remote_configuration_environment(self):
        with patch.dict(os.environ, {"OPENAI_FEED_PATH": "XML/OPENAI/custom.xml"}):
            self.assertEqual(
                run_daily.configured_feed_path("OPENAI"),
                Path("XML/OPENAI/custom.xml"),
            )


if __name__ == "__main__":
    unittest.main()
