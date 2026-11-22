"""Convert article DOM to portable HTML while retaining its semantic structure."""
import html
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


BLOCKS = {
    'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li',
    'pre', 'figure', 'figcaption', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
}
INLINE = {'strong', 'b', 'em', 'i', 'code', 's', 'del', 'sub', 'sup', 'br', 'hr'}


def _url(value: str, base_url: str) -> str:
    if not value.strip():
        return ''
    full = urljoin(base_url, value)
    return full if urlparse(full).scheme in {'https', 'http'} else ''


def clean_article_html(source: str, base_url: str = '') -> str | None:
    """Drop site chrome; retain paragraph boundaries, nested markup and inline media."""
    soup = BeautifulSoup(source, 'lxml')
    root = soup.select_one('main article, article')
    if root is None:
        root = soup.select_one('[data-toc-content]')
    if root is None:
        return None
    if any(t in root.get_text() for t in ('Verification successful', 'Waiting for openai.com')):
        return None
    for dead in list(root.select(
        'script, style, nav, header, footer, button, aside, svg, '
        '[role="navigation"], [aria-label="breadcrumb"], '
        '[data-section-header], [data-article-hero-actions], '
        '[data-testid="author-list"], [data-testid="citations"], '
        '[data-testid="testimonial-carousel-controls"], '
        '[data-analytics="b2b-customer-story-prefooter"], .sr-only, '
        '[aria-hidden="true"]:not(figure), [aria-label="Testimonials"]'
    )):
        dead.decompose()
    for heading in list(root.find_all(['h2', 'h3'])):
        if heading.name is None:
            continue
        if heading.get_text(' ', strip=True).casefold() in {'keep reading', 'related articles'}:
            current = heading
            while current is not root:
                for sibling in list(current.next_siblings):
                    sibling.extract()
                current = current.parent
            heading.decompose()

    def render(node) -> str:
        if isinstance(node, Comment):
            return ''
        if isinstance(node, NavigableString):
            return html.escape(str(node))
        if not isinstance(node, Tag):
            return ''
        tag = node.name
        if tag == 'img':
            src = _url(node.get('src') or node.get('data-src') or '', base_url)
            if not src:
                return ''
            return (f'<img src="{html.escape(src, quote=True)}" '
                    f'alt="{html.escape(node.get("alt") or "", quote=True)}" '
                    'style="max-width:100%;display:block">')
        inner = ''.join(render(c) for c in node.children)
        if tag == 'a':
            href = _url(node.get('href') or '', base_url)
            return f'<a href="{html.escape(href, quote=True)}">{inner}</a>' if href else inner
        if tag in INLINE:
            return f'<{tag}>' if tag in {'br', 'hr'} else f'<{tag}>{inner}</{tag}>'
        if tag in BLOCKS:
            if not inner.strip():
                return ''
            attrs = ''
            if tag in {'th', 'td'}:
                for key in ('colspan', 'rowspan'):
                    value = str(node.get(key) or '')
                    if value.isdigit():
                        attrs += f' {key}="{value}"'
            if tag == 'ol' and str(node.get('start') or '').isdigit():
                attrs += f' start="{node["start"]}"'
            if tag == 'figure':
                attrs += ' style="margin:1.5em 0"'
            return f'<{tag}{attrs}>{inner}</{tag}>'
        return inner

    result = render(root).strip()
    return result if result and root.select_one('p, h2, h3, figure, table, ul, ol') else None
