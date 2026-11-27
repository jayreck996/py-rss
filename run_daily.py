"""
Aggregated daily fetch: Anthropic, OpenAI, Coinbase, Nintendo, Binance.
Each source runs independently — a failure in one does not stop the others.
Writes per-source XML feeds to the XML/ submodule for Pages.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse
import html as html_module
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

from bs4 import BeautifulSoup

from ANTHROPIC.claude import CATEGORY_API, is_article_url, listing_resources
from COINBASE.extractor import discover_listing as coinbase_discover_listing
from NINTENDO.extractor import discover_listing as nintendo_discover_listing

DATA_DIR = Path("data")


def configured_feed_path(source: str) -> Path:
    variable = f"{source.upper()}_FEED_PATH"
    value = os.environ.get(variable, "")
    if not value:
        raise RuntimeError(f"{variable} is required; load YML/PY-RSS/<feed>/YML.yml first")
    return Path(value)


def configured_feed_meta(source: str) -> dict:
    p = source.upper()
    return {
        "listing_url":   os.environ.get(f"{p}_LISTING_URL", ""),
        "title":         os.environ.get(f"{p}_CHANNEL_TITLE", ""),
        "link":          os.environ.get(f"{p}_CHANNEL_LINK", ""),
        "description":   os.environ.get(f"{p}_CHANNEL_DESCRIPTION", ""),
        "self_href":     os.environ.get(f"{p}_CHANNEL_SELF_HREF", ""),
        "window_days":   int(os.environ.get(f"{p}_WINDOW_DAYS", "7")),
    }


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def url_to_slug(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return re.sub(r"[^a-zA-Z0-9_-]", "-", path)


def _body_to_html(text: str, cover_url: str = "") -> str:
    if not text.strip().startswith("<"):
        raise ValueError("Structured article HTML is required")
    inline_bases = {u.split("?")[0] for u in re.findall(r'<img[^>]+src=["\']([^"\']+)', text)}
    cover_html = ""
    if cover_url and cover_url.split("?")[0] not in inline_bases:
        cover_html = (
            f'<img src="{html_module.escape(cover_url, quote=True)}" '
            'style="max-width:100%;display:block;margin-bottom:1em">'
        )
    return cover_html + text


def _write_feed(rss: Element, destination: Path) -> None:
    xml_str = parseString(tostring(rss, encoding="unicode")).toprettyxml(indent="  ")
    xml_str = xml_str.replace("&lt;![CDATA[", "<![CDATA[").replace("]]&gt;", "]]>")
    xml_str = re.sub(
        r"<!\[CDATA\[(.*?)]]>",
        lambda m: f"<![CDATA[{html_module.unescape(m.group(1))}]]>",
        xml_str,
        flags=re.DOTALL,
    )
    destination.write_text(xml_str, encoding="utf-8")


def _build_rss(title: str, link: str, description: str, self_href: str) -> tuple[Element, Element, Element]:
    rss = Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")
    rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = title
    SubElement(channel, "link").text = link
    SubElement(channel, "description").text = description
    SubElement(channel, "language").text = "en"
    SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(tz=timezone.utc))
    atom_link = SubElement(channel, "atom:link")
    atom_link.set("href", self_href)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")
    return rss, channel, atom_link


def _add_items(channel: Element, articles: list[dict]) -> None:
    for a in articles:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = a.get("title") or "Untitled"
        SubElement(item, "link").text = a.get("url", "")
        SubElement(item, "guid", isPermaLink="false").text = a.get("url", "")
        SubElement(item, "description").text = a.get("summary") or ""
        body = a.get("body_text", "")
        cover = (a.get("cover_image") or {}).get("url", "")
        if body:
            try:
                html_body = _body_to_html(body, cover)
                encoded = SubElement(item, "content:encoded")
                encoded.text = f"<![CDATA[{html_body}]]>"
            except ValueError:
                pass
        if a.get("published_at"):
            try:
                dt = datetime.fromisoformat(a["published_at"].replace("Z", "+00:00"))
                SubElement(item, "pubDate").text = format_datetime(dt)
            except Exception:
                pass
        if cover:
            enc = SubElement(item, "enclosure")
            enc.set("url", cover)
            enc.set("type", "image/jpeg")
            enc.set("length", "0")


def _cleanup_old_data(data_dir: Path) -> None:
    if not data_dir.exists():
        return
    cutoff = date.today() - timedelta(days=WINDOW_DAYS)
    for day_dir in sorted(data_dir.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            if date.fromisoformat(day_dir.name) < cutoff:
                shutil.rmtree(day_dir)
                print(f"Removed expired data: {day_dir}")
        except ValueError:
            pass


def _load_articles(data_dir: Path) -> list[dict]:
    articles = []
    for f in sorted(data_dir.glob("**/*.json"), reverse=True):
        try:
            article = json.loads(f.read_text(encoding="utf-8"))
            body = article.get("body_text") or ""
            if body and not body.strip().startswith("<"):
                print(f"Skipped {f.name}: structured article HTML is invalid")
                continue
            articles.append(article)
        except Exception:
            continue
    return articles


# ---------------------------------------------------------------------------
# ANTHROPIC runner
# ---------------------------------------------------------------------------

def _anthropic_read_listing(listing_url: str) -> tuple[list, int]:
    req = urllib.request.Request(listing_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return listing_resources(response.read().decode("utf-8"))


def _anthropic_read_page(page_number: int) -> tuple[list, int]:
    query = urlencode({"page": page_number, "language": "en", "type": "articles"})
    req = urllib.request.Request(
        CATEGORY_API + "?" + query,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": ANTHROPIC_URL},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.load(response)
    if not isinstance(data.get("items"), list) or not isinstance(data.get("total"), int):
        raise ValueError("Claude pagination returned an invalid resource page")
    return data["items"], data["total"]


async def _discover_anthropic(listing_url: str, window_days: int) -> list[str]:
    items, total = _anthropic_read_listing(listing_url)
    cutoff = date.today() - timedelta(days=window_days)
    urls: list[str] = []
    seen: set[str] = set()
    seen_pages: set[tuple] = set()
    page_number = 1
    while items:
        signature = tuple((item.get("slug"), item.get("externalUrl"), item.get("date")) for item in items)
        if signature in seen_pages:
            raise ValueError("Claude article pagination did not advance")
        seen_pages.add(signature)
        reached_cutoff = False
        for item in items:
            published = item.get("date")
            if not published:
                continue
            if date.fromisoformat(published[:10]) < cutoff:
                reached_cutoff = True
                continue
            if item.get("externalUrl"):
                continue
            slug = item.get("slug")
            if not isinstance(slug, str):
                continue
            url = listing_url + "/" + slug
            if is_article_url(url) and url not in seen:
                seen.add(url)
                urls.append(url)
        if reached_cutoff or page_number >= total:
            break
        page_number += 1
        items, total = _anthropic_read_page(page_number)
    return urls


async def run_anthropic(test_version: int | None = None) -> None:
    from ANTHROPIC.extractor import extract

    meta = configured_feed_meta("ANTHROPIC")
    data_dir = DATA_DIR / "ANTHROPIC"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[ANTHROPIC] Discovering: {meta['listing_url']}")
    urls = await _discover_anthropic(meta["listing_url"], meta["window_days"])
    print(f"[ANTHROPIC] Found {len(urls)} links")

    today = date.today().isoformat()
    out_dir = data_dir / today
    out_dir.mkdir(parents=True, exist_ok=True)

    for url in urls:
        print(f"[ANTHROPIC]   -> {url}")
        try:
            article = await extract(url, use_cache=False)
            if not article.published_at:
                article.published_at = date.today().isoformat()
            try:
                pub_date = date.fromisoformat(article.published_at[:10])
                if pub_date < date.today() - timedelta(days=meta["window_days"]):
                    print(f"[ANTHROPIC]     Skipped (older than {meta['window_days']} days)")
                    continue
            except ValueError:
                pass
            slug = url_to_slug(url)
            dest = out_dir / f"{slug}.json"
            dest.write_text(article.model_dump_json(indent=2), encoding="utf-8")
            print(f"[ANTHROPIC]     Saved: {dest.name}")
        except Exception as exc:
            print(f"[ANTHROPIC]     ERROR: {exc}", file=sys.stderr)

    _cleanup_old_data(data_dir)
    articles = _load_articles(data_dir)

    rss, channel, atom_link = _build_rss(
        meta["title"], meta["link"], meta["description"], meta["self_href"],
    )
    _add_items(channel, articles)
    feed_path = configured_feed_path("ANTHROPIC")
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    _write_feed(rss, feed_path)
    print(f"[ANTHROPIC] Feed updated: {len(articles)} item(s) -> {feed_path}")

    if test_version is not None:
        test_name = f"feed_v{test_version}_anthropic.xml"
        atom_link.set("href", atom_link.get("href").rsplit("/", 1)[0] + "/" + test_name)
        for guid in channel.findall("item/guid"):
            guid.text += f"#v{test_version}"
        _write_feed(rss, Path(test_name))


# ---------------------------------------------------------------------------
# OPENAI runner
# ---------------------------------------------------------------------------

def _discover_openai(listing_url: str, window_days: int) -> list[tuple[str, str, str]]:
    req = urllib.request.Request(
        listing_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; RSS reader)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read()
    soup = BeautifulSoup(content, "xml")
    cutoff = date.today() - timedelta(days=window_days)
    seen: set[str] = set()
    items: list[tuple[str, str, str]] = []
    for item in soup.find_all("item"):
        link_tag = item.find("link")
        pub_tag = item.find("pubDate")
        title_tag = item.find("title")
        if not link_tag:
            continue
        url = link_tag.text.strip().rstrip("/")
        path = urlparse(url).path.rstrip("/")
        if not re.match(r"^/(index|blog|research)/[^/]+$", path):
            continue
        pub_iso = ""
        if pub_tag:
            try:
                dt = parsedate_to_datetime(pub_tag.text)
                if dt.date() < cutoff:
                    break
                pub_iso = dt.date().isoformat()
            except Exception:
                pass
        rss_title = title_tag.text.strip() if title_tag else ""
        if url not in seen:
            seen.add(url)
            items.append((url, pub_iso, rss_title))
    return items


async def run_openai(test_version: int | None = None) -> None:
    from OPENAI.extractor import extract

    meta = configured_feed_meta("OPENAI")
    data_dir = DATA_DIR / "OPENAI"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[OPENAI] Discovering from RSS: {meta['listing_url']}")
    found = _discover_openai(meta["listing_url"], meta["window_days"])
    print(f"[OPENAI] Found {len(found)} links")
    rss_dates = {url: pub_iso for url, pub_iso, _ in found}
    rss_titles = {url: title for url, _, title in found}
    urls = list(dict.fromkeys(url for url, _, _ in found))

    today = date.today().isoformat()
    out_dir = data_dir / today
    out_dir.mkdir(parents=True, exist_ok=True)

    for url in urls:
        print(f"[OPENAI]   -> {url}")
        try:
            article = await extract(url, use_cache=False)
            blocked = (
                not article.title
                or "Verification successful" in (article.body_text or "")
                or "Waiting for openai.com" in (article.body_text or "")
            )
            if blocked:
                import json as _json
                fallback_title = rss_titles.get(url) or urlparse(url).path.split("/")[-1].replace("-", " ").title()
                fallback_pub = rss_dates.get(url) or date.today().isoformat()
                slug = url_to_slug(url)
                dest = out_dir / f"{slug}.json"
                dest.write_text(_json.dumps({"url": url, "source": "openai", "title": fallback_title, "published_at": fallback_pub, "body_text": None}, indent=2), encoding="utf-8")
                print(f"[OPENAI]     Cloudflare blocked — saved RSS metadata only")
                continue
            if not article.published_at and rss_dates.get(url):
                article.published_at = rss_dates[url]
            if article.published_at:
                try:
                    pub_date = date.fromisoformat(article.published_at[:10])
                    if pub_date < date.today() - timedelta(days=meta["window_days"]):
                        print(f"[OPENAI]     Skipped (older than {meta['window_days']} days)")
                        continue
                except ValueError:
                    pass
            slug = url_to_slug(url)
            dest = out_dir / f"{slug}.json"
            dest.write_text(article.model_dump_json(indent=2), encoding="utf-8")
            print(f"[OPENAI]     Saved: {dest.name}")
        except Exception as exc:
            print(f"[OPENAI]     ERROR: {exc}", file=sys.stderr)

    _cleanup_old_data(data_dir)
    articles = _load_articles(data_dir)

    rss, channel, atom_link = _build_rss(
        meta["title"], meta["link"], meta["description"], meta["self_href"],
    )
    _add_items(channel, articles)
    feed_path = configured_feed_path("OPENAI")
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    _write_feed(rss, feed_path)
    print(f"[OPENAI] Feed updated: {len(articles)} item(s) -> {feed_path}")

    if test_version is not None:
        test_name = f"feed_v{test_version}_openai.xml"
        atom_link.set("href", atom_link.get("href").rsplit("/", 1)[0] + "/" + test_name)
        for guid in channel.findall("item/guid"):
            guid.text += f"#v{test_version}"
        _write_feed(rss, Path(test_name))


# ---------------------------------------------------------------------------
# COINBASE runner
# ---------------------------------------------------------------------------

async def run_coinbase(test_version: int | None = None) -> None:
    from COINBASE.extractor import extract

    meta = configured_feed_meta("COINBASE")
    data_dir = DATA_DIR / "COINBASE"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[COINBASE] Discovering from: {meta['listing_url']}")
    found = await coinbase_discover_listing()
    print(f"[COINBASE] Found {len(found)} links")

    today = date.today().isoformat()
    out_dir = data_dir / today
    out_dir.mkdir(parents=True, exist_ok=True)

    for url in found:
        print(f"[COINBASE]   -> {url}")
        try:
            article = await extract(url, use_cache=False)
            if not article.published_at:
                article.published_at = date.today().isoformat()
            try:
                pub_date = date.fromisoformat(article.published_at[:10])
                if pub_date < date.today() - timedelta(days=meta["window_days"]):
                    print(f"[COINBASE]     Skipped (older than {meta['window_days']} days)")
                    continue
            except ValueError:
                pass
            slug = url_to_slug(url)
            dest = out_dir / f"{slug}.json"
            dest.write_text(article.model_dump_json(indent=2), encoding="utf-8")
            print(f"[COINBASE]     Saved: {dest.name}")
        except Exception as exc:
            print(f"[COINBASE]     ERROR: {exc}", file=sys.stderr)

    _cleanup_old_data(data_dir)
    articles = _load_articles(data_dir)

    rss, channel, atom_link = _build_rss(
        meta["title"], meta["link"], meta["description"], meta["self_href"],
    )
    _add_items(channel, articles)
    feed_path = configured_feed_path("COINBASE")
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    _write_feed(rss, feed_path)
    print(f"[COINBASE] Feed updated: {len(articles)} item(s) -> {feed_path}")

    if test_version is not None:
        test_name = f"feed_v{test_version}_coinbase.xml"
        atom_link.set("href", atom_link.get("href").rsplit("/", 1)[0] + "/" + test_name)
        for guid in channel.findall("item/guid"):
            guid.text += f"#v{test_version}"
        _write_feed(rss, Path(test_name))


# ---------------------------------------------------------------------------
# NINTENDO runner
# ---------------------------------------------------------------------------

async def run_nintendo(test_version: int | None = None) -> None:
    from NINTENDO.extractor import extract

    meta = configured_feed_meta("NINTENDO")
    data_dir = DATA_DIR / "NINTENDO"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[NINTENDO] Discovering from: {meta['listing_url']}")
    found = await nintendo_discover_listing()
    print(f"[NINTENDO] Found {len(found)} links")

    today = date.today().isoformat()
    out_dir = data_dir / today
    out_dir.mkdir(parents=True, exist_ok=True)

    for url in found:
        print(f"[NINTENDO]   -> {url}")
        try:
            article = await extract(url, use_cache=False)
            if not article.published_at:
                article.published_at = date.today().isoformat()
            try:
                pub_date = date.fromisoformat(article.published_at[:10])
                if pub_date < date.today() - timedelta(days=meta["window_days"]):
                    print(f"[NINTENDO]     Skipped (older than {meta['window_days']} days)")
                    continue
            except ValueError:
                pass
            slug = url_to_slug(url)
            dest = out_dir / f"{slug}.json"
            dest.write_text(article.model_dump_json(indent=2), encoding="utf-8")
            print(f"[NINTENDO]     Saved: {dest.name}")
        except Exception as exc:
            print(f"[NINTENDO]     ERROR: {exc}", file=sys.stderr)

    _cleanup_old_data(data_dir)
    articles = _load_articles(data_dir)

    rss, channel, atom_link = _build_rss(
        meta["title"], meta["link"], meta["description"], meta["self_href"],
    )
    _add_items(channel, articles)
    feed_path = configured_feed_path("NINTENDO")
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    _write_feed(rss, feed_path)
    print(f"[NINTENDO] Feed updated: {len(articles)} item(s) -> {feed_path}")

    if test_version is not None:
        test_name = f"feed_v{test_version}_nintendo.xml"
        atom_link.set("href", atom_link.get("href").rsplit("/", 1)[0] + "/" + test_name)
        for guid in channel.findall("item/guid"):
            guid.text += f"#v{test_version}"
        _write_feed(rss, Path(test_name))


async def run_binance(test_version: int | None = None) -> None:
    from binance.extractor import fetch_articles

    meta = configured_feed_meta("BINANCE")
    articles = await fetch_articles()
    cutoff = date.today() - timedelta(days=meta["window_days"])
    articles = [
        article for article in articles
        if date.fromisoformat(article["published_at"][:10]) >= cutoff
    ]
    articles.sort(key=lambda article: article["published_at"], reverse=True)

    rss, channel, atom_link = _build_rss(
        meta["title"], meta["link"], meta["description"], meta["self_href"],
    )
    _add_items(channel, articles)
    feed_path = configured_feed_path("BINANCE")
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    _write_feed(rss, feed_path)
    print(f"[BINANCE] Feed updated: {len(articles)} item(s) -> {feed_path}")

    if test_version is not None:
        test_name = f"feed_v{test_version}_binance.xml"
        atom_link.set("href", atom_link.get("href").rsplit("/", 1)[0] + "/" + test_name)
        for guid in channel.findall("item/guid"):
            guid.text += f"#v{test_version}"
        _write_feed(rss, Path(test_name))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main(test_version: int | None = None, feed_only: bool = False) -> None:
    if test_version is not None and test_version < 1:
        raise ValueError("Test feed version must be a positive integer")

    failures: list[str] = []

    sources = [
        ("ANTHROPIC", run_anthropic),
        ("OPENAI", run_openai),
        ("COINBASE", run_coinbase),
        ("NINTENDO", run_nintendo),
        ("BINANCE", run_binance),
    ]
    for name, run in sources:
        try:
            await run(test_version)
        except Exception as exc:
            print(f"\n[{name}] FAILED: {exc}", file=sys.stderr)
            failures.append(name)

    if failures:
        print(f"\nFailed sources: {', '.join(failures)}", file=sys.stderr)
        if len(failures) == len(sources):
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aggregate RSS feeds from Anthropic, OpenAI, Coinbase, Nintendo, Binance.")
    parser.add_argument("--feed-only", action="store_true", help="Rebuild feeds from saved data without fetching.")
    parser.add_argument("--test-version", type=int, metavar="N")
    args = parser.parse_args()
    if args.test_version is not None and args.test_version < 1:
        parser.error("--test-version must be a positive integer")
    asyncio.run(main(args.test_version, args.feed_only))
