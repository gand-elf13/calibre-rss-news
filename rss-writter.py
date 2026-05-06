# rss_writer.py – generate Atom feed XML from article data

import html
import re
from datetime import datetime, timezone


def _esc(s):
    return html.escape(str(s or ''), quote=True)


def _atom_date(dt=None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    if not hasattr(dt, 'strftime'):
        # string → parse
        try:
            from dateutil.parser import parse as _p
            dt = _p(str(dt))
        except Exception:
            dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def write_atom_feed(recipe_title, recipe_url, articles, description='', language='en'):
    """
    articles: list of dicts with keys:
        title, url, content_html, pub_date (str|datetime), author, description
    Returns: Atom XML string (UTF-8)
    """
    now = _atom_date()
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="{lang}">'.format(lang=_esc(language)),
        '  <title>{}</title>'.format(_esc(recipe_title)),
        '  <id>{}</id>'.format(_esc(recipe_url or f'urn:calibre-rss:{recipe_title}')),
        '  <updated>{}</updated>'.format(now),
    ]
    if description:
        lines.append('  <subtitle>{}</subtitle>'.format(_esc(description)))

    for art in articles:
        pub = _atom_date(art.get('pub_date'))
        url = _esc(art.get('url', ''))
        title = _esc(art.get('title') or '(no title)')
        author = _esc(art.get('author') or '')
        content = art.get('content_html') or art.get('description') or ''
        # CDATA is safest for arbitrary HTML content
        content_cdata = content.replace(']]>', ']]>]]><![CDATA[')

        lines.append('  <entry>')
        lines.append('    <title>{}</title>'.format(title))
        lines.append('    <id>{}</id>'.format(url or f'urn:calibre-rss:entry:{pub}'))
        lines.append('    <link href="{}" rel="alternate"/>'.format(url))
        lines.append('    <updated>{}</updated>'.format(pub))
        if author:
            lines.append('    <author><name>{}</name></author>'.format(author))
        if art.get('description'):
            lines.append('    <summary>{}</summary>'.format(_esc(art['description'])))
        if content:
            lines.append('    <content type="html"><![CDATA[{}]]></content>'.format(content_cdata))
        lines.append('  </entry>')

    lines.append('</feed>')
    return '\n'.join(lines)
