import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext, async_playwright

LISTING_URL = "https://www.binance.com/en/blog"
ARTICLE_PATH = re.compile(r"/en/blog/[a-z0-9-]+/[0-9]{10,}/?")


def article_urls(html: str) -> list[str]:
    urls = {}
    for link in BeautifulSoup(html, "lxml").select("a[href]"):
        url = urlsplit(urljoin(LISTING_URL, link["href"]))
        if url.netloc == "www.binance.com" and ARTICLE_PATH.fullmatch(url.path):
            canonical = urlunsplit(("https", url.netloc, url.path.rstrip("/"), "", ""))
            urls[canonical] = None
    return list(urls)


def article_body(soup: BeautifulSoup, url: str) -> str:
    for unwanted in soup.select("script, style, nav, header, footer, aside, iframe, form, button, noscript"):
        unwanted.decompose()

    body = next(
        (
            container for container in soup.select(
                '[itemprop="articleBody"], [class*="article-body"], '
                '[class*="articleBody"], [class*="article-content"], [class*="articleContent"]'
            )
            if container.find("p")
        ),
        None,
    )
    if body is None:
        paragraphs = [p for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        if len(paragraphs) >= 2:
            for parent in paragraphs[0].parents:
                if parent.name in {"body", "html", "[document]"}:
                    break
                if sum(parent in p.parents for p in paragraphs) >= max(2, len(paragraphs) * 0.8):
                    body = parent
                    break
    if body is None:
        raise ValueError("Binance article body is missing")

    allowed_attributes = {
        "a": {"href", "title"},
        "img": {"src", "alt", "title", "width", "height"},
        "td": {"colspan", "rowspan"},
        "th": {"colspan", "rowspan", "scope"},
    }
    for tag in body.find_all(True):
        attributes = allowed_attributes.get(tag.name, set())
        tag.attrs = {name: value for name, value in tag.attrs.items() if name in attributes}
        for attribute in ("href", "src"):
            if value := tag.get(attribute):
                absolute = urljoin(url, value)
                if urlsplit(absolute).scheme in {"http", "https"}:
                    tag[attribute] = absolute
                else:
                    del tag[attribute]
    return body.decode_contents().strip()


def parse_article(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    heading = soup.find("h1")
    if not heading:
        raise ValueError("Binance article heading is missing")

    def meta(name: str) -> str:
        tag = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name})
        return tag.get("content", "").strip() if tag else ""

    published = meta("article:published_time")
    if not published:
        time_tag = soup.select_one("article time[datetime], main time[datetime], time[datetime]")
        if time_tag:
            published = time_tag["datetime"]
    if not published:
        for value in heading.find_all_next(string=True, limit=30):
            if value.parent.name not in {"script", "style"} and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
                published = value.strip()
                break
    if not published:
        raise ValueError("Binance article publication date is missing")

    datetime.fromisoformat(published.replace("Z", "+00:00"))
    image = meta("og:image")
    return {
        "url": url,
        "source": "binance",
        "title": heading.get_text(" ", strip=True),
        "published_at": published,
        "summary": meta("og:description") or meta("description"),
        "body_text": article_body(soup, url),
        "cover_image": {"url": urljoin(url, image)} if image else None,
    }


async def page_html(context: BrowserContext, url: str, selector: str) -> str:
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_selector(selector, state="attached", timeout=20_000)
        return await page.content()
    finally:
        await page.close()


async def fetch_articles() -> list[dict]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(locale="en-NZ")
        try:
            listing = await page_html(context, LISTING_URL, 'a[href*="/en/blog/"]')
            urls = article_urls(listing)
            if not urls:
                raise ValueError("Binance blog returned no article links")
            articles = []
            for url in urls:
                try:
                    articles.append(parse_article(await page_html(context, url, "h1"), url))
                except Exception as exc:
                    print(f"[BINANCE] {url}: {exc}")
            if not articles:
                raise ValueError("Binance blog returned no readable articles")
            return articles
        finally:
            await browser.close()
