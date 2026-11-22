"""Strict adapters for Claude's article listing and rendered rich-text payload."""
import html
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .flight import FlightTree, read_records

LISTING_URL = 'https://claude.com/resources/articles'
CATEGORY_API = 'https://claude.com/api/resources/category'
ALLOWED_HOSTS = {'claude.com', 'www.claude.com'}


def is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname in ALLOWED_HOSTS
            and bool(re.fullmatch(r'/resources/articles/[a-z0-9][a-z0-9-]*/?', parsed.path)))


def listing_resources(source: str) -> tuple[list, int]:
    """Read the featured article and initial page from the listing component."""
    records = read_records(source)
    tree = FlightTree(records)
    for value in records.values():
        for node, _ in tree.elements(value):
            props = node[3]
            scope = props.get('scope')
            curated = props.get('curated')
            if (isinstance(scope, dict) and scope.get('kind') == 'type'
                    and scope.get('pathSlug') == 'articles' and isinstance(curated, dict)):
                items = curated.get('items')
                total = curated.get('total')
                if not isinstance(items, list) or not isinstance(total, int):
                    raise ValueError('Claude article listing has an invalid resource page')
                lead = curated.get('lead')
                return ([lead] if isinstance(lead, dict) else []) + items, total
    raise ValueError('Claude structured article listing was not found')


def article_author(soup: BeautifulSoup) -> str | None:
    for item in soup.select('[class*="DetailSidebar"][class*="__item"]'):
        label = item.select_one('[class*="__label"]')
        value = item.select_one('[class*="__value"]')
        if label and value and label.get_text(strip=True) == 'Author':
            return value.get_text(' ', strip=True) or None
    return None


class _ClaudeTree(FlightTree):
    def render(self, value, active=frozenset(), depth=0):
        value, active = self.resolve(value, active)
        if depth > 100:
            return ''
        if isinstance(value, list) and len(value) >= 4 and value[0] == '$' and isinstance(value[3], dict):
            props = value[3]
            annotation = props.get('value')
            if isinstance(annotation, dict) and annotation.get('_type') == 'link':
                label = self.render(props.get('children'), active, depth + 1)
                href = annotation.get('href')
                return f'<a href="{html.escape(href, quote=True)}">{label}</a>' if isinstance(href, str) else label
            if props.get('type') == 'youtubeEmbed':
                video_id = props.get('youtubeId')
                if isinstance(video_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
                    label = html.escape(props.get('alt') or 'Watch video')
                    return f'<figure><a href="https://www.youtube.com/watch?v={video_id}">Video: {label}</a></figure>'
            video_url = props.get('videoUrl')
            if isinstance(video_url, str) and video_url.startswith('https://'):
                label = html.escape(props.get('alt') or 'Watch video')
                return f'<figure><a href="{html.escape(video_url, quote=True)}">Video: {label}</a></figure>'
        return super().render(value, active, depth)


def extract_claude_body(source: str, base_url: str) -> str | None:
    """Use only the article rich-text component; never substitute arbitrary DOM."""
    records = read_records(source)
    tree = _ClaudeTree(records)
    for value in records.values():
        for node, active in tree.elements(value):
            classes = node[3].get('className')
            if not isinstance(classes, str) or 'text-rich-text--article' not in classes.split():
                continue
            soup = BeautifulSoup(tree.render(node, active), 'lxml')
            root = soup.select_one('.text-rich-text--article')
            if root is None or not root.select_one('p, h2, h3, figure, ul, ol, table'):
                return None
            for dead in list(root.select('script, style, nav, button, svg, .sr-only')):
                dead.decompose()
            for element in root.find_all(True):
                attributes = {}
                for key in ('href', 'src', 'alt', 'title', 'colspan', 'rowspan', 'start'):
                    val = element.get(key)
                    if val is None:
                        continue
                    if key in {'href', 'src'}:
                        val = urljoin(base_url, val)
                        if urlparse(val).scheme not in {'https', 'http'}:
                            continue
                    attributes[key] = val
                if element.name == 'img':
                    attributes['style'] = 'max-width:100%;display:block'
                element.attrs = attributes
            if not root.get_text(strip=True) and not root.select_one('img'):
                return None
            return '<article>' + ''.join(str(child) for child in root.contents) + '</article>'
    return None
