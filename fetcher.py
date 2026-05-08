# fetcher.py – fetches and cleans article HTML from a loaded recipe instance

import re
import logging
from urllib.parse import urljoin

try:
    from curl_cffi import requests
    _IMPERSONATE = "chrome124"
except ImportError:
    import requests
    _IMPERSONATE = None

from bs4 import BeautifulSoup

try:
    from readability import Document as ReadabilityDoc
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False

logger = logging.getLogger("fetcher")

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

TIMEOUT = (15, 30)  # (connect_timeout, read_timeout) in seconds
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB cap per article


def _decode_response(raw_bytes, encoding=None):
    """
    Robustly decode HTTP response bytes to text.
    Tries UTF-8 first (which is the modern standard), then falls back
    to the specified encoding or common legacy encodings.
    """
    if isinstance(raw_bytes, str):
        return raw_bytes

    # First try UTF-8 (most common for modern APIs)
    try:
        return raw_bytes.decode('utf-8')
    except UnicodeDecodeError:
        pass

    # If encoding is explicitly specified and it's a known legacy encoding, try it
    if encoding and encoding.lower() not in ('utf-8', 'utf8'):
        try:
            return raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass

    # Try Windows-1252 (common fallback for Western European text)
    try:
        return raw_bytes.decode('windows-1252')
    except UnicodeDecodeError:
        pass

    # Last resort: decode with replacement characters
    return raw_bytes.decode('utf-8', errors='replace')


def _do_get(url, session, encoding):
    """Inner fetch — runs in a thread so we can enforce a hard wall-clock timeout."""
    # Handle file:/// URLs written by recipes like economist (print_version temp files)
    if url.startswith('file:///') or url.startswith('file://'):
        import urllib.request, urllib.parse
        path = urllib.parse.urlparse(url).path
        # Python 3.14+ url2pathname rejects paths starting with //
        # (urlparse('file:////tmp/foo').path → '//tmp/foo')
        if path.startswith('//'):
            path = path[1:]
        local_path = urllib.request.url2pathname(path)
        with open(local_path, 'rb') as f:
            raw = f.read()
        return _decode_response(raw, encoding), url
    if session is not None:
        s = session
    elif _IMPERSONATE:
        from curl_cffi.requests import Session as _S
        s = _S(impersonate=_IMPERSONATE)
        s.headers['User-Agent'] = DEFAULT_UA
    else:
        s = requests.Session()
        s.headers['User-Agent'] = DEFAULT_UA
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True)
    r.raise_for_status()
    chunks = []
    size = 0
    for chunk in r.iter_content(chunk_size=65536):
        if chunk:
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_RESPONSE_BYTES:
                logger.warning(f"Response truncated at {MAX_RESPONSE_BYTES // 1024}KB: {url}")
                break
    raw_bytes = b"".join(chunks)
    # Use robust decoding: prefer UTF-8, then fallback to specified encoding
    return _decode_response(raw_bytes, encoding or r.apparent_encoding), r.url


def _get(url, session=None, encoding=None):
    """Fetch with a hard wall-clock timeout enforced via a thread."""
    import concurrent.futures as _cf
    HARD_TIMEOUT = 45  # seconds total per article fetch
    with _cf.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_do_get, url, session, encoding)
        try:
            return fut.result(timeout=HARD_TIMEOUT)
        except _cf.TimeoutError:
            raise TimeoutError(f"Hard timeout ({HARD_TIMEOUT}s) fetching {url}")


def _tag_matches(tag, spec):
    """
    Check whether a BS4 tag matches a calibre tag spec.
    spec can be:
      - str: tag name
      - dict with optional 'name', 'attrs', 'class'
      - callable
    """
    if callable(spec):
        return bool(spec(tag))
    if isinstance(spec, str):
        return tag.name == spec
    if isinstance(spec, dict):
        name = spec.get('name')
        if name and tag.name != name:
            return False
        attrs = spec.get('attrs', {})
        for attr, val in attrs.items():
            tag_val = tag.get(attr, '')
            if callable(val):
                # value can be a function (used by classes() helper)
                if isinstance(tag_val, list):
                    if not val(set(tag_val)):
                        return False
                else:
                    if not val({tag_val}):
                        return False
            elif isinstance(val, (list, tuple)):
                tag_val_set = set(tag_val) if isinstance(tag_val, list) else {tag_val}
                if not any(v in tag_val_set for v in val):
                    return False
            else:
                if isinstance(tag_val, list):
                    if val not in tag_val:
                        return False
                elif tag_val != val:
                    return False
        return True
    return False


def _apply_keep_only_tags(soup, specs):
    """Keep only content inside matching tags; discard everything else."""
    if not specs:
        return soup
    found = []
    for spec in specs:
        found.extend(soup.find_all(
            spec if isinstance(spec, str) else spec.get('name', True),
            attrs=spec.get('attrs', {}) if isinstance(spec, dict) else {}
        ))
    if not found:
        return soup
    # Rebuild body with only matched fragments
    body = soup.find('body') or soup
    body.clear()
    for tag in found:
        body.append(tag)
    return soup


def _apply_remove_tags(soup, specs):
    for spec in specs:
        if isinstance(spec, str):
            for t in soup.find_all(spec):
                t.decompose()
        elif isinstance(spec, dict):
            name = spec.get('name', True)
            attrs = spec.get('attrs', {})
            for t in soup.find_all(name, attrs=attrs):
                t.decompose()
    return soup


def _apply_remove_tags_before(soup, specs):
    for spec in specs:
        name  = spec.get('name', True) if isinstance(spec, dict) else spec
        attrs = spec.get('attrs', {}) if isinstance(spec, dict) else {}
        marker = soup.find(name, attrs=attrs)
        if marker:
            for sib in list(marker.find_all_previous()):
                sib.decompose()
    return soup


def _apply_remove_tags_after(soup, specs):
    for spec in specs:
        name  = spec.get('name', True) if isinstance(spec, dict) else spec
        attrs = spec.get('attrs', {}) if isinstance(spec, dict) else {}
        marker = soup.find(name, attrs=attrs)
        if marker:
            for sib in list(marker.find_all_next()):
                sib.decompose()
    return soup


def _apply_preprocess_regexps(html, regexps):
    for pat, repl in regexps:
        if callable(repl):
            html = pat.sub(repl, html)
        else:
            html = pat.sub(repl, html)
    return html


def _auto_cleanup(html, url, keep_selector=None):
    """Use readability-lxml for main-content extraction."""
    if not HAS_READABILITY:
        return html
    try:
        doc = ReadabilityDoc(html, url=url)
        cleaned = doc.summary(html_partial=True)
        return cleaned
    except Exception as e:
        logger.debug(f"readability failed on {url}: {e}")
        return html


def _no_stylesheets(soup):
    for tag in soup.find_all('link', rel=lambda v: v and 'stylesheet' in v):
        tag.decompose()
    for tag in soup.find_all('style'):
        tag.decompose()
    return soup


def _remove_javascript(soup):
    for tag in soup.find_all('script'):
        tag.decompose()
    for tag in soup.find_all(onload=True):
        del tag['onload']
    return soup


def _make_absolute_urls(soup, base_url):
    for tag in soup.find_all('img', src=True):
        tag['src'] = urljoin(base_url, tag['src'])
    for tag in soup.find_all('a', href=True):
        tag['href'] = urljoin(base_url, tag['href'])
    return soup


def fetch_article(url, recipe, session=None):
    """
    Fetch and clean a single article according to recipe rules.
    Returns (cleaned_html_str, final_url) or (None, url) on failure.
    """
    try:
        # Allow recipe to rewrite URL (e.g. print version)
        url = recipe.print_version(url) or url

        # Use the recipe's own browser session so UA, cookies and headers
        # set in get_browser() apply to article fetches too.
        if session is None:
            br = recipe.get_browser()
            session = getattr(br, '_session', None)

        raw_html, final_url = _get(url, session=session, encoding=recipe.encoding)

        # preprocess_regexps
        if recipe.preprocess_regexps:
            raw_html = _apply_preprocess_regexps(raw_html, recipe.preprocess_regexps)

        # preprocess_raw_html hook — this is where recipes like economist
        # convert JSON/API responses into HTML. Must NOT be silently swallowed.
        try:
            result = recipe.preprocess_raw_html(raw_html, final_url)
            if result is not None:
                # Recipes may return an lxml element (via etree.tostring) or a string
                if not isinstance(result, str):
                    try:
                        from lxml import etree
                        result = etree.tostring(result, encoding='unicode',
                                                method='html')
                    except Exception:
                        result = str(result)
                raw_html = result
        except Exception as e:
            logger.warning(f"preprocess_raw_html failed for {final_url}: {e}")
            import traceback; logger.debug(traceback.format_exc())

        # auto_cleanup via readability
        if recipe.auto_cleanup:
            raw_html = _auto_cleanup(raw_html, final_url, recipe.auto_cleanup_keep)

        soup = BeautifulSoup(raw_html, 'lxml')

        # remove stylesheets
        if recipe.no_stylesheets:
            _no_stylesheets(soup)

        # remove javascript
        if recipe.remove_javascript:
            _remove_javascript(soup)

        # remove_tags_before / after
        if recipe.remove_tags_before:
            _apply_remove_tags_before(soup, recipe.remove_tags_before)
        if recipe.remove_tags_after:
            _apply_remove_tags_after(soup, recipe.remove_tags_after)

        # keep_only_tags
        if recipe.keep_only_tags:
            _apply_keep_only_tags(soup, recipe.keep_only_tags)

        # remove_tags
        if recipe.remove_tags:
            _apply_remove_tags(soup, recipe.remove_tags)

        # make image/link URLs absolute
        _make_absolute_urls(soup, final_url)

        # recipe hook
        try:
            soup = recipe.preprocess_html(soup) or soup
        except Exception:
            pass

        # Extract the useful part
        body = soup.find('body')
        if body:
            content_html = body.decode_contents()
        else:
            content_html = str(soup)

        return content_html, final_url

    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None, url
