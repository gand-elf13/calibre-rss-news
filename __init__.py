# calibre_compat/__init__.py
# Emulates calibre module imports so .recipe files load without Calibre installed.

import sys
import types
import tempfile
import re
import time
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("calibre_compat")

# ---------------------------------------------------------------------------
# Lightweight logger shim (calibre uses log.warn / log() directly)
# ---------------------------------------------------------------------------

class CalibreLog:
    def __call__(self, *args):
        logger.info(" ".join(str(a) for a in args))
    def info(self, *args):
        logger.info(" ".join(str(a) for a in args))
    def warn(self, *args):
        logger.warning(" ".join(str(a) for a in args))
    def warning(self, *args):
        logger.warning(" ".join(str(a) for a in args))
    def error(self, *args):
        logger.error(" ".join(str(a) for a in args))
    def debug(self, *args):
        logger.debug(" ".join(str(a) for a in args))
    def exception(self, *args):
        logger.exception(" ".join(str(a) for a in args))


# ---------------------------------------------------------------------------
# Browser shim
# ---------------------------------------------------------------------------

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

class Browser:
    """Minimal mechanize-compatible browser shim."""
    def __init__(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = DEFAULT_UA

    def open(self, url, data=None, timeout=30):
        if data:
            r = self._session.post(url, data=data, timeout=timeout)
        else:
            r = self._session.get(url, timeout=timeout)
        r.raise_for_status()
        return BrowserResponse(r)

    def open_novisit(self, url, data=None, timeout=30):
        return self.open(url, data, timeout)

    def set_simple_cookie(self, name, value, domain):
        self._session.cookies.set(name, value, domain=domain)

    def addheaders(self, headers):
        for k, v in headers:
            self._session.headers[k] = v

    def select_form(self, *args, **kwargs):
        pass  # stub

    def __setitem__(self, key, value):
        pass  # stub for form field assignment

    def submit(self):
        pass  # stub

    def clone_browser(self):
        b = Browser()
        b._session.cookies.update(self._session.cookies)
        b._session.headers.update(self._session.headers)
        return b

    def get_cookiejar(self):
        return self._session.cookies

    def set_cookiejar(self, cj):
        self._session.cookies = cj


class BrowserResponse:
    def __init__(self, response):
        self._r = response

    def read(self):
        return self._r.content

    def get_data(self):
        return self._r.text

    @property
    def url(self):
        return self._r.url


# ---------------------------------------------------------------------------
# PersistentTemporaryFile shim
# ---------------------------------------------------------------------------

class PersistentTemporaryFile:
    def __init__(self, suffix='', prefix='tmp', dir=None):
        self._f = tempfile.NamedTemporaryFile(
            suffix=suffix, prefix=prefix, dir=dir, delete=False
        )
        self.name = self._f.name

    def write(self, data):
        return self._f.write(data)

    def read(self):
        self._f.seek(0)
        return self._f.read()

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# ---------------------------------------------------------------------------
# Article abort sentinel
# ---------------------------------------------------------------------------

class AbortArticle(Exception):
    pass


# ---------------------------------------------------------------------------
# BasicNewsRecipe
# ---------------------------------------------------------------------------

class BasicNewsRecipe:
    # ---- class-level defaults (recipes override these) ----
    title           = "Unnamed Recipe"
    description     = ""
    __author__      = ""
    language        = "en"
    oldest_article  = 7          # days
    max_articles_per_feed = 100
    no_stylesheets  = True
    remove_javascript = True
    auto_cleanup    = False
    auto_cleanup_keep = None
    use_embedded_content = None  # None → auto-detect
    encoding        = None       # None → auto-detect
    feeds           = []
    keep_only_tags  = []
    remove_tags     = []
    remove_tags_after  = []
    remove_tags_before = []
    filter_regexps  = []
    match_regexps   = []
    preprocess_regexps  = []
    extra_css       = ""
    needs_subscription  = False
    remove_empty_feeds  = True
    delay           = 0
    simultaneous_downloads = 5
    timefmt         = " [%a, %d %b %Y]"
    masthead_url    = None
    cover_url       = None
    browser_type    = "mechanize"
    resolve_internal_links = False
    recursions      = 0

    def __init__(self):
        self.log   = CalibreLog()
        self._br   = None
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=self.oldest_article)

    # ---- browser ----

    def get_browser(self):
        if self._br is None:
            self._br = Browser()
        return self._br

    get_browser.is_base_class_implementation = True

    def clone_browser(self, br):
        return br.clone_browser()

    @property
    def browser(self):
        return self.get_browser()

    # ---- feed list ----

    def get_feeds(self):
        return self.feeds

    # ---- article URL hook ----

    def get_article_url(self, article):
        link = getattr(article, 'link', None) or article.get('url', '')
        return link

    def print_version(self, url):
        return url

    # ---- HTML hooks ----

    def preprocess_html(self, soup):
        return soup

    def postprocess_html(self, soup, first_fetch):
        return soup

    def preprocess_raw_html(self, raw_html, url):
        return raw_html

    # ---- metadata hook ----

    def populate_article_metadata(self, article, soup, first):
        pass

    # ---- index / parsing ----

    def parse_index(self):
        """Override to return [(feed_title, [article_dict, ...]), ...]"""
        return None

    # ---- abort helpers ----

    def abort_article(self, msg='abort'):
        raise AbortArticle(msg)

    def abort_recipe_processing(self, msg='abort'):
        raise RuntimeError(f"Recipe aborted: {msg}")

    # ---- utility ----

    def index_to_soup(self, url_or_html, raw=False):
        if url_or_html.strip().startswith('<'):
            html = url_or_html
        else:
            br = self.get_browser()
            resp = br.open(url_or_html)
            raw_bytes = resp.read()
            enc = self.encoding or 'utf-8'
            html = raw_bytes.decode(enc, errors='replace')
        if raw:
            return html
        return BeautifulSoup(html, 'lxml')

    def tag_to_string(self, tag, use_alt=True, normalize_whitespace=True):
        if tag is None:
            return ''
        if isinstance(tag, str):
            return tag
        text = tag.get_text()
        if normalize_whitespace:
            text = re.sub(r'\s+', ' ', text).strip()
        return text

    def get_encoding(self):
        return self.encoding or 'utf-8'

    def sleep(self, n):
        time.sleep(n)

    def add_toc_thumbnail(self, article, src):
        pass  # not needed for RSS output

    def cleanup(self):
        pass

    # ---- internal helper used by the runner ----

    def _is_article_old(self, pub_date_str):
        if not pub_date_str:
            return False
        try:
            from dateutil.parser import parse as _parse
            dt = _parse(pub_date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt < self._cutoff
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Stub for calibre.utils.date
# ---------------------------------------------------------------------------

def parse_date(date_str, assume_utc=False, as_utc=True, default=None):
    if not date_str:
        return default or datetime.now(timezone.utc)
    try:
        from dateutil.parser import parse as _parse
        dt = _parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return default or datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# classes() helper used by many recipes
# ---------------------------------------------------------------------------

def classes(*args):
    """Return a dict{attrs: {'class': True}} suitable for keep_only_tags etc."""
    q = frozenset(args)
    def check(x):
        return bool(x.intersection(q)) if x else False
    return {'attrs': {'class': check}}


# ---------------------------------------------------------------------------
# Wire up fake calibre.* module hierarchy
# ---------------------------------------------------------------------------

def _stub_module(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

def install():
    """Call once to inject all calibre stubs into sys.modules."""
    if 'calibre' in sys.modules:
        return  # already installed

    calibre            = _stub_module('calibre')
    calibre_web        = _stub_module('calibre.web')
    calibre_web_feeds  = _stub_module('calibre.web.feeds')
    calibre_web_feeds_news = _stub_module('calibre.web.feeds.news')
    calibre_ebooks     = _stub_module('calibre.ebooks')
    calibre_ebooks_bs  = _stub_module('calibre.ebooks.BeautifulSoup')
    calibre_ebooks_hp  = _stub_module('calibre.ebooks.oeb')
    calibre_browser    = _stub_module('calibre.browser')
    calibre_ptmp       = _stub_module('calibre.ptempfile')
    calibre_utils      = _stub_module('calibre.utils')
    calibre_utils_log  = _stub_module('calibre.utils.logging')
    calibre_utils_date = _stub_module('calibre.utils.date')
    calibre_utils_img  = _stub_module('calibre.utils.img')
    calibre_customize  = _stub_module('calibre.customize')
    calibre_utils_fmt  = _stub_module('calibre.utils.formatter_functions')

    # Attach key symbols
    calibre_web_feeds_news.BasicNewsRecipe = BasicNewsRecipe
    calibre_web_feeds_news.classes         = classes
    calibre_web_feeds_news.prefixed_classes = classes  # alias
    calibre_ebooks_bs.BeautifulSoup        = BeautifulSoup
    calibre_browser.Browser                = Browser
    calibre_ptmp.PersistentTemporaryFile   = PersistentTemporaryFile
    calibre_ptmp.TemporaryDirectory        = tempfile.TemporaryDirectory
    calibre_utils_log.GUILog               = CalibreLog
    calibre_utils_log.Log                  = CalibreLog
    calibre_utils_date.parse_date          = parse_date
    calibre_utils_date.strftime            = lambda fmt, dt=None: (dt or datetime.now()).strftime(fmt)
    calibre.strftime                       = lambda fmt, dt=None: (dt or datetime.now()).strftime(fmt)
    calibre.random_user_agent              = lambda **kw: DEFAULT_UA
    calibre.preferred_encoding             = 'utf-8'
    calibre.force_unicode                  = lambda s, enc='utf-8': s if isinstance(s, str) else s.decode(enc, 'replace')
    calibre.as_unicode                     = calibre.force_unicode
    calibre.iswindows                      = False
    calibre.__appname__                    = 'calibre'
    calibre_utils_img.scale_image          = lambda *a, **kw: b''
    calibre_customize.Plugin               = object
    calibre_customize.FileTypePlugin       = object
