import json
import re
import time
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .models import Article, Image

_cache: dict[str, tuple[float, Article]] = {}
CACHE_TTL = 3600

LISTING_URL = "https://www.nintendo.com/au/news-and-articles/"


async def discover_listing() -> list[str]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                extra_http_headers={
                    "Accept-Language": "en-AU,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await ctx.new_page()
            await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60_000)
            try:
                await page.wait_for_selector("a[href*='/news-and-articles/']", timeout=15_000)
            except Exception:
                pass
            html = await page.content()
        finally:
            await browser.close()

    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.match(r"^/au/news-and-articles/[^/]+/?$", href):
            full = f"https://www.nintendo.com{href.rstrip('/')}/"
            if full not in seen:
                seen.add(full)
                urls.append(full)
        elif re.match(r"^https://www\.nintendo\.com/au/news-and-articles/[^/]+/?$", href):
            full = href.rstrip("/") + "/"
            if full not in seen:
                seen.add(full)
                urls.append(full)
    return urls


async def extract(url: str, *, use_cache: bool = True) -> Article:
    if use_cache and url in _cache:
        ts, article = _cache[url]
        if time.time() - ts < CACHE_TTL:
            return article

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                extra_http_headers={
                    "Accept-Language": "en-AU,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                },
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                await page.wait_for_selector("article, main p, .article-body", timeout=15_000)
            except Exception:
                pass
            html = await page.content()
        finally:
            await browser.close()

    soup = BeautifulSoup(html, "lxml")

    body_text = _extract_body(soup, url)
    if not body_text:
        raise ValueError("Article content was not found; article skipped")

    title = (
        _meta(soup, "og:title")
        or _meta(soup, "twitter:title")
        or _jsonld_field(soup, "headline")
        or (soup.h1.get_text(strip=True) if soup.h1 else None)
    )
    summary = (
        _meta(soup, "og:description")
        or _meta(soup, "description")
        or _jsonld_field(soup, "description")
    )
    author = _jsonld_author(soup) or _meta(soup, "author")
    published_at = (
        _meta(soup, "article:published_time")
        or _jsonld_field(soup, "datePublished")
        or _jsonld_field(soup, "dateCreated")
    )
    og_image = _meta(soup, "og:image") or _meta(soup, "twitter:image")
    cover_image = Image(url=og_image) if og_image else None
    images = _body_images(BeautifulSoup(f"<article>{body_text}</article>", "lxml"), url)

    article = Article(
        url=url,
        title=title,
        author=author,
        published_at=published_at,
        summary=summary,
        cover_image=cover_image,
        body_html=body_text,
        body_text=body_text,
        images=images,
    )
    _cache[url] = (time.time(), article)
    return article


def _extract_body(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    for selector in (
        "[class*='articleBody']",
        "[class*='article-body']",
        "[class*='ArticleBody']",
        "[class*='article-content']",
        "[class*='ArticleContent']",
        "[class*='news-body']",
        "[class*='NewsBody']",
        "article",
        "main article",
    ):
        el = soup.select_one(selector)
        if el:
            el = _clean(el)
            text = el.decode_contents().strip()
            if len(text) > 200:
                return text

    # Last-resort: find the <main> sub-element with the most paragraph text
    main = soup.select_one("main")
    if main:
        main = _clean(main)
        # Pick the direct child block with the most text
        best, best_len = None, 0
        for child in main.find_all(["section", "div"], recursive=False):
            _clean(child)
            t = child.get_text(strip=True)
            if len(t) > best_len:
                best, best_len = child, len(t)
        if best and best_len > 200:
            return best.decode_contents().strip()
    return None


def _clean(el):
    for tag in el.find_all(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    # Remove elements that look like menus (many sibling links with short text)
    for tag in el.find_all(True):
        links = tag.find_all("a", recursive=False)
        if len(links) >= 5 and all(len(a.get_text(strip=True)) < 40 for a in links):
            tag.decompose()
    return el


def _meta(soup: BeautifulSoup, name: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"property": name}) or soup.find(
        "meta", attrs={"name": name}
    )
    return tag.get("content", "").strip() or None if tag else None


def _jsonld_field(soup: BeautifulSoup, field: str) -> Optional[str]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            for item in data.get("@graph", [data]):
                if isinstance(item, dict) and field in item:
                    val = item[field]
                    if isinstance(val, str):
                        return val.strip() or None
        except (json.JSONDecodeError, AttributeError):
            continue
    return None


def _jsonld_author(soup: BeautifulSoup) -> Optional[str]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            for item in data.get("@graph", [data]):
                if not isinstance(item, dict):
                    continue
                author = item.get("author")
                if isinstance(author, dict):
                    return author.get("name", "").strip() or None
                if isinstance(author, list):
                    names = [a.get("name", "") for a in author if isinstance(a, dict)]
                    return ", ".join(filter(None, names)) or None
        except (json.JSONDecodeError, AttributeError):
            continue
    return None


def _body_images(soup: BeautifulSoup, base_url: str) -> list[Image]:
    images: list[Image] = []
    seen: set[str] = set()
    container = soup.select_one("article") or soup.select_one("main")
    if not container:
        return images
    for img in container.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or src in seen:
            continue
        seen.add(src)
        full = urljoin(base_url, src) if not src.startswith("http") else src
        try:
            w = int(img.get("width", 0)) or None
            h = int(img.get("height", 0)) or None
        except (ValueError, TypeError):
            w = h = None
        images.append(Image(url=full, alt=img.get("alt"), width=w, height=h))
    return images
