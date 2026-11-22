"""Read article content from a React Flight tree in document order."""
import html
import json
import re

from .rendering import clean_article_html


_PUSH = re.compile(r'__next_f\.push\(\s*\[\s*1\s*,\s*("(?:[^"\\]|\\.)*")\s*\]\s*\)')
_REF = re.compile(r'^\$(?:L|@)?([0-9a-f]+)(?::(.*))?$')
_TAGS = {
    'article', 'main', 'section', 'div', 'span', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'blockquote', 'figure', 'figcaption', 'a', 'img', 'strong', 'b',
    'em', 'i', 'pre', 'code', 'br', 'hr', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'td',
    'th', 'sup', 'sub', 's', 'del', 'nav', 'header', 'footer', 'aside', 'button', 'script',
}


def _records(source: str) -> dict:
    payload = ''.join(json.loads(m.group(1)) for m in _PUSH.finditer(source))
    wire = payload.encode('utf-8')
    records = {}
    consumed = 0
    decoder = json.JSONDecoder()
    for match in re.finditer(rb'(?:\A|\n)([0-9a-f]+):', wire):
        if match.start() < consumed:
            continue
        start = match.end()
        key = match.group(1).decode()
        text_header = re.match(rb'T([0-9a-f]+),', wire[start:])
        if text_header:
            text_start = start + text_header.end()
            consumed = text_start + int(text_header.group(1), 16)
            records[key] = wire[text_start:consumed].decode('utf-8')
            continue
        try:
            records[key] = decoder.raw_decode(wire[start:].decode('utf-8'))[0]
        except (ValueError, UnicodeDecodeError):
            continue
    return records


class _Tree:
    def __init__(self, records: dict):
        self.records = records

    def resolve(self, value, active=frozenset()):
        if not isinstance(value, str):
            return value, active
        match = _REF.fullmatch(value)
        if not match:
            return value, active
        key, path = match.groups()
        if key in active or key not in self.records:
            return None, active
        value = self.records[key]
        active = active | {key}
        if path:
            for part in path.split(':'):
                value, active = self.resolve(value, active)
                if isinstance(value, dict):
                    value = value.get(part)
                elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                    value = value[int(part)]
                else:
                    return None, active
        return self.resolve(value, active)

    def elements(self, value, active=frozenset(), depth=0):
        if depth > 100:
            return
        value, active = self.resolve(value, active)
        if isinstance(value, list):
            if len(value) >= 4 and value[0] == '$' and isinstance(value[3], dict):
                yield value, active
                for child in value[3].values():
                    yield from self.elements(child, active, depth + 1)
            else:
                for child in value:
                    yield from self.elements(child, active, depth + 1)
        elif isinstance(value, dict):
            for child in value.values():
                yield from self.elements(child, active, depth + 1)

    def image(self, props, active, depth):
        asset = props
        for name in ('image', 'asset', 'file'):
            candidate, _ = self.resolve(asset.get(name), active)
            if isinstance(candidate, dict):
                asset = candidate
        src, _ = self.resolve(asset.get('url') or asset.get('src'), active)
        if not isinstance(src, str) or not src.startswith(('https://', 'http://', '//')):
            return ''
        alt, _ = self.resolve(props.get('altText') or props.get('alt') or asset.get('altText') or '', active)
        if isinstance(alt, str) and alt.startswith('$'):
            alt = ''
        caption = self.render(props.get('caption'), active, depth + 1)
        image = f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(str(alt or ""), quote=True)}">'
        return '<figure>' + image + (f'<figcaption>{caption}</figcaption>' if caption else '') + '</figure>'

    def render(self, value, active=frozenset(), depth=0):
        if depth > 100:
            return ''
        value, active = self.resolve(value, active)
        if value is None or isinstance(value, bool):
            return ''
        if isinstance(value, str):
            if value.startswith('$$'):
                value = value[1:]
            elif value.startswith('$'):
                return ''
            return html.escape(value)
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            if len(value) < 4 or value[0] != '$' or not isinstance(value[3], dict):
                return ''.join(self.render(v, active, depth + 1) for v in value)
            _, kind, _, props, *_ = value
            tag = props.get('headlineTag') or props.get('as') or props.get('tag') or kind
            if not isinstance(tag, str) or tag not in _TAGS:
                tag = 'a' if props.get('variant') == 'inline' and props.get('href') else None
            if tag == 'img':
                attrs = ''
                for key in ('src', 'alt'):
                    val, _ = self.resolve(props.get(key), active)
                    if isinstance(val, str):
                        attrs += f' {key}="{html.escape(val, quote=True)}"'
                return f'<img{attrs}>'
            if tag is None and any(k in props for k in ('image', 'asset', 'url', 'src')):
                image = self.image(props, active, depth)
                if image:
                    return image
            children = props.get('children', props.get('text'))
            inner = self.render(children, active, depth + 1)
            if tag is None:
                tag = 'p' if 'text' in props else None
            if tag is None:
                return inner
            attrs = ''
            for key, val in props.items():
                if key in {'href', 'className', 'role', 'colSpan', 'rowSpan', 'start'} or key.startswith(('data-', 'aria-')):
                    val, _ = self.resolve(val, active)
                    if isinstance(val, (str, int, bool)):
                        name = {'className': 'class', 'colSpan': 'colspan', 'rowSpan': 'rowspan'}.get(key, key)
                        attrs += f' {name}="{html.escape(str(val).lower() if isinstance(val, bool) else str(val), quote=True)}"'
            return f'<{tag}{attrs}>' if tag in {'br', 'hr'} else f'<{tag}{attrs}>{inner}</{tag}>'
        if isinstance(value, dict):
            return self.image(value, active, depth)
        return ''


def extract_rsc_article(source: str, base_url: str = '') -> str | None:
    """Follow rendered child references, never the order records arrived over the wire."""
    records = _records(source)
    tree = _Tree(records)
    candidates = []
    for value in records.values():
        for node, active in tree.elements(value):
            if node[1] == 'article':
                candidates.insert(0, (node, active))
            elif node[1] == 'main':
                candidates.append((node, active))
    for node, active in candidates:
        markup = tree.render(node, active)
        if node[1] == 'main':
            markup = '<article>' + markup + '</article>'
        body = clean_article_html(markup, base_url)
        if body:
            return f"<article>{body}</article>"
    return None
