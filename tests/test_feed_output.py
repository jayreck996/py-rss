import json
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

    def _patch(self):
        return patch.object(run_daily, "DATA_DIR", self.root / "data"), \
               patch.object(run_daily, "Path", side_effect=lambda name: self.root / name)

    def test_per_source_feeds_written(self):
        p1, p2 = self._patch()
        with p1, p2:
            articles = run_daily._load_articles(self.root / "data" / "ANTHROPIC")
            rss, channel, _ = run_daily._build_rss("T", "http://x", "D", "http://x/feed.xml")
            run_daily._add_items(channel, articles)
            feed_path = self.root / "XML" / "ANTHROPIC" / "XML-2026Q4.xml"
            feed_path.parent.mkdir(parents=True, exist_ok=True)
            run_daily._write_feed(rss, feed_path)
        tree = ET.parse(feed_path)
        self.assertEqual(tree.findtext("./channel/item/guid"), self.urls["ANTHROPIC"])

    def test_combined_feed_merges_all_sources(self):
        all_articles = []
        for source in ("ANTHROPIC", "OPENAI", "COINBASE"):
            all_articles.extend(run_daily._load_articles(self.root / "data" / source))
        with patch.object(run_daily, "Path", side_effect=lambda name: self.root / name):
            run_daily._generate_combined_feed(all_articles)
        combined = ET.parse(self.root / "XML" / "COMBINED" / "XML-2026Q4.xml")
        guids = {item.text for item in combined.findall("./channel/item/guid")}
        self.assertEqual(guids, set(self.urls.values()))

    def test_source_failure_does_not_affect_combined(self):
        all_articles = run_daily._load_articles(self.root / "data" / "ANTHROPIC")
        with patch.object(run_daily, "Path", side_effect=lambda name: self.root / name):
            run_daily._generate_combined_feed(all_articles)
        combined = ET.parse(self.root / "XML" / "COMBINED" / "XML-2026Q4.xml")
        items = combined.findall("./channel/item")
        self.assertEqual(len(items), 1)

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


if __name__ == "__main__":
    unittest.main()
