# calibre_compat/__init__.py
# Emulates calibre.* imports so any .recipe file loads without Calibre installed.
#
# Symbols covered (sourced by auditing the full calibre recipe collection):
#   calibre.web.feeds.news      – BasicNewsRecipe, classes, prefixed_classes
#   calibre.web.feeds.recipes   – alias of above
#   calibre.utils.date          – local_tz, utc_tz, parse_date, strptime,
#                                  parse_only_date, strftime, isoformat, now
#   calibre.utils.random_ua     – common_english_word_ua,
#                                  random_common_chrome_user_agent
#   calibre.utils.cleantext     – clean_ascii_chars, clean_xml_chars
#   calibre.utils.logging       – Log, GUILog
#   calibre.utils.img           – scale_image
#   calibre.ebooks.BeautifulSoup– BeautifulSoup, NavigableString, Tag, CData
#   calibre.browser             – browser() factory + Browser class
#   calibre.ptempfile           – PersistentTemporaryFile, TemporaryDirectory
#   calibre.customize           – Plugin, FileTypePlugin
#   polyglot.functools          – lru_cache
#   polyglot.builtins           – as_bytes, as_unicode, iteritems …
#   mechanize                   – Request (pass-through to real mechanize)
#   html5_parser                – parse (fallback via lxml)

import sys
import types
import tempfile
import re
import time
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from functools import lru_cache

try:
    from curl_cffi import requests
    from curl_cffi.requests import Session as _Session
    _IMPERSONATE = "chrome124"
except ImportError:
    import requests
    _Session = requests.Session
    _IMPERSONATE = None

from bs4 import BeautifulSoup, NavigableString, Tag, CData

logger = logging.getLogger("calibre_compat")

# ---------------------------------------------------------------------------
# Timezone objects
# ---------------------------------------------------------------------------

local_tz = datetime.now().astimezone().tzinfo
utc_tz   = timezone.utc

# ---------------------------------------------------------------------------
# Logger shim
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
        import traceback, sys
        msg = " ".join(str(a) for a in args)
        exc = sys.exc_info()
        if exc[0] is not None:
            # Called from inside an except block — show full traceback
            tb = "".join(traceback.format_exception(*exc))
            logger.error(f"{msg}\n{tb}")
        else:
            logger.error(msg)

# ---------------------------------------------------------------------------
# User-agent helpers
# ---------------------------------------------------------------------------

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Calibre's word-based UA: two random common English words joined by '/'
# e.g. "investor/theme", "decide/age" — used to avoid bot detection
_COMMON_WORDS = (
    'ability','able','accept','account','across','action','activity','address',
    'administration','adult','affect','agency','agent','agree','agreement','air',
    'allow','amount','analysis','animal','answer','approach','area','argue','arm',
    'article','artist','assume','attack','attention','attorney','audience','author',
    'avoid','baby','bank','base','beat','behavior','believe','benefit','bill',
    'billion','blood','board','body','book','born','break','bring','brother',
    'budget','build','business','camera','campaign','candidate','capital','career',
    'carry','cause','cell','center','chance','change','character','charge','child',
    'choice','church','citizen','city','civil','claim','clear','coach','collection',
    'college','color','common','community','company','concern','condition',
    'conference','consider','consumer','continue','control','cost','country',
    'couple','course','court','cover','create','crime','culture','current',
    'customer','dark','daughter','dead','deal','death','debate','decade','decide',
    'decision','deep','defense','degree','describe','design','detail','determine',
    'develop','development','difference','dinner','direction','discover','discuss',
    'disease','doctor','draw','dream','drive','drop','drug','early','east',
    'economic','economy','edge','education','effect','effort','election','employee',
    'energy','enjoy','enter','environment','establish','evening','event','evidence',
    'example','executive','exist','expect','experience','explain','factor','fail',
    'fall','family','fear','federal','feeling','field','financial','fine','firm',
    'floor','focus','follow','force','foreign','forget','forward','free','friend',
    'front','fund','future','garden','glass','goal','government','green','ground',
    'group','grow','growth','guess','gun','hand','happen','health','heart','heavy',
    'history','hold','home','hope','hospital','house','human','identify','image',
    'imagine','impact','improve','include','increase','industry','information',
    'interest','international','interview','invest','investor','issue','join',
    'kill','land','laugh','lead','learn','leave','legal','level','light','likely',
    'listen','local','lose','love','machine','magazine','maintain','major',
    'majority','manage','material','media','medical','meeting','member','memory',
    'mention','message','military','million','mind','minute','miss','model',
    'morning','mother','move','music','nation','national','natural','nature',
    'network','news','night','notice','occur','offer','office','option','order',
    'organization','owner','parent','partner','party','patient','peace','perform',
    'period','phone','picture','piece','plant','point','police','policy','position',
    'power','practice','prepare','present','price','private','problem','process',
    'produce','product','program','project','property','provide','purpose',
    'quality','quickly','race','rate','reach','reason','recent','reduce','reflect',
    'relate','remain','report','represent','require','research','resource','respond',
    'result','return','reveal','risk','role','rule','scene','school','season',
    'sense','serve','service','share','shoot','short','sign','situation','skill',
    'social','society','soldier','sort','sound','south','space','speak','special',
    'specific','spend','staff','stage','stand','state','stay','strategy','street',
    'structure','student','study','style','subject','success','summer','support',
    'surface','system','teacher','team','technology','television','tend','term',
    'theory','thought','thousand','threat','together','total','tough','trade',
    'treat','trial','trouble','type','understand','unit','value','view','voice',
    'vote','watch','water','week','west','wind','woman','wonder','work','world',
    'worry','write','year',
)

def common_english_word_ua():
    """Mimic calibre's word-based UA: 'word/word' e.g. 'investor/theme'."""
    import random
    return '{}/{}'.format(random.choice(_COMMON_WORDS), random.choice(_COMMON_WORDS))

def random_common_chrome_user_agent():
    """Return a varied Chrome UA, matching calibre's random chrome UA pool."""
    import random
    versions = [
        'Chrome/120.0.0.0', 'Chrome/121.0.0.0', 'Chrome/122.0.0.0',
        'Chrome/123.0.0.0', 'Chrome/124.0.0.0', 'Chrome/125.0.0.0',
        'Chrome/134.0.0.0', 'Chrome/135.0.0.0',
    ]
    platforms = [
        ('Windows NT 10.0; Win64; x64', 'Windows NT 10.0; Win64; x64'),
        ('X11; Linux x86_64', 'X11; Linux x86_64'),
        ('Macintosh; Intel Mac OS X 10_15_7', 'Macintosh; Intel Mac OS X 10_15_7'),
    ]
    plat_ua, _ = random.choice(platforms)
    ver = random.choice(versions)
    return (f'Mozilla/5.0 ({plat_ua}) AppleWebKit/537.36 '
            f'(KHTML, like Gecko) {ver} Safari/537.36')

def random_user_agent(allow_ie=False):
    return DEFAULT_UA

# ---------------------------------------------------------------------------
# Browser shim
# ---------------------------------------------------------------------------

class BrowserResponse:
    def __init__(self, response):
        self._r = response
    def read(self):
        return self._r.content
    def get_data(self):
        return self._r.text
    def geturl(self):
        return self._r.url
    @property
    def url(self):
        return self._r.url
    @property
    def status_code(self):
        return self._r.status_code
    def raise_for_status(self):
        self._r.raise_for_status()
    def info(self):
        return self
    def get(self, header, default=None):
        return self._r.headers.get(header, default)


class Browser:
    """Minimal mechanize-like browser backed by curl_cffi (TLS-impersonating) or requests."""

    def __init__(self, user_agent=DEFAULT_UA, **kwargs):
        if _IMPERSONATE:
            self._session = _Session(impersonate=_IMPERSONATE)
        else:
            self._session = _Session()
        self._session.headers['User-Agent'] = user_agent
        self._current_url = None

    def open(self, url_or_request, data=None, timeout=30):
        url = getattr(url_or_request, 'get_full_url',
                      lambda: url_or_request)()
        headers = {}
        if hasattr(url_or_request, 'headers'):
            headers = dict(url_or_request.headers)
        if data:
            r = self._session.post(url, data=data, headers=headers, timeout=timeout)
        else:
            r = self._session.get(url, headers=headers, timeout=timeout)
        # Do NOT call raise_for_status() here — recipes often wrap open() in
        # try/except and need to inspect or handle non-200 responses themselves.
        # Callers that require a clean response (e.g. fetcher.py) check status
        # explicitly after calling open().
        self._current_url = r.url
        return BrowserResponse(r)

    def open_novisit(self, url, data=None, timeout=30):
        return self.open(url, data, timeout)

    def open_with_retry(self, url, **kwargs):
        return self.open(url, **kwargs)

    def select_form(self, *a, **kw): pass
    def __setitem__(self, key, value): pass
    def submit(self, *a, **kw):
        return BrowserResponse(requests.Response())

    def set_simple_cookie(self, name, value, domain='', path='/'):
        self._session.cookies.set(name, value, domain=domain, path=path)

    def set_cookie(self, name, value, domain='', path='/'):
        """mechanize alias for set_simple_cookie."""
        self._session.cookies.set(name, value, domain=domain, path=path)
    def addheaders(self, headers):
        for k, v in headers:
            self._session.headers[k] = v
    def set_cookiejar(self, cj):
        self._session.cookies = cj
    def get_cookiejar(self):
        return self._session.cookies

    def clone_browser(self):
        b = Browser(user_agent=self._session.headers.get('User-Agent', DEFAULT_UA))
        b._session.cookies.update(self._session.cookies)
        b._session.headers.update(self._session.headers)
        return b

    def geturl(self):
        return self._current_url or ''
    def reload(self): pass
    def back(self): pass


def browser(*args, **kwargs):
    """Module-level factory: `from calibre import browser; br = browser()`"""
    return Browser(*args, **kwargs)

# ---------------------------------------------------------------------------
# PersistentTemporaryFile
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
# Date utilities
# ---------------------------------------------------------------------------

def parse_date(date_str, assume_utc=False, as_utc=True, default=None):
    if not date_str:
        return default or datetime.now(utc_tz)
    try:
        from dateutil.parser import parse as _p
        dt = _p(str(date_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=utc_tz if assume_utc else local_tz)
        return dt
    except Exception:
        return default or datetime.now(utc_tz)

def strptime(date_str, fmt, assume_utc=False):
    try:
        dt = datetime.strptime(date_str, fmt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=utc_tz if assume_utc else local_tz)
        return dt
    except Exception:
        return datetime.now(utc_tz)

def parse_only_date(date_str, assume_utc=True):
    return parse_date(date_str, assume_utc=assume_utc)

def strftime(fmt, dt=None):
    return (dt or datetime.now()).strftime(fmt)

def isoformat(dt, sep='T'):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=utc_tz)
    return dt.isoformat(sep)

def now():
    return datetime.now(utc_tz)

# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

def clean_ascii_chars(text):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text or '')

def prepare_string_for_xml(s, attribute=False):
    import html
    return html.escape(str(s or ''), quote=attribute)

def force_unicode(s, enc='utf-8'):
    if isinstance(s, bytes):
        return s.decode(enc, 'replace')
    return str(s)

as_unicode = force_unicode

# ---------------------------------------------------------------------------
# Abort sentinel
# ---------------------------------------------------------------------------

class AbortArticle(Exception):
    pass

class NoArticles(Exception):
    """Raised by recipes when no articles are found (e.g. paywall/network)."""
    pass

# ---------------------------------------------------------------------------
# classes() / prefixed_classes() helpers
# ---------------------------------------------------------------------------

def classes(*args):
    """
    Return a BS4 find() spec dict matching any of the given CSS class names.
    Accepts both variadic args AND a single space-separated string.
    """
    if len(args) == 1 and isinstance(args[0], str) and ' ' in args[0]:
        q = frozenset(args[0].split())
    else:
        q = frozenset(args)

    def check(x):
        if not x:
            return False
        if isinstance(x, str):
            return bool(q.intersection(x.split()))
        try:
            return bool(q.intersection(x))
        except TypeError:
            return False

    return {'attrs': {'class': check}}


def prefixed_classes(classes_str):
    """Match tags whose class starts with any prefix in the space-separated string.
    Mirrors real calibre: prefixed_classes('Foo__ Bar__') matches class='Foo__xyz'.
    """
    prefixes = tuple(classes_str.split())

    def check(x):
        if not x:
            return False
        vals = x.split() if isinstance(x, str) else list(x)
        return any(v.startswith(prefixes) for v in vals)

    return {'attrs': {'class': check}}

# ---------------------------------------------------------------------------
# BasicNewsRecipe
# ---------------------------------------------------------------------------

class BasicNewsRecipe:
    title                  = "Unnamed Recipe"
    description            = ""
    __author__             = ""
    language               = "en"
    oldest_article         = 7
    max_articles_per_feed  = 100
    no_stylesheets         = True
    remove_javascript      = True
    auto_cleanup           = False
    auto_cleanup_keep      = None
    use_embedded_content   = None
    encoding               = None
    feeds                  = []
    keep_only_tags         = []
    remove_tags            = []
    remove_tags_after      = []
    remove_tags_before     = []
    filter_regexps         = []
    match_regexps          = []
    preprocess_regexps     = []
    extra_css              = ""
    needs_subscription     = False
    remove_empty_feeds     = True
    delay                  = 0
    simultaneous_downloads = 5
    timefmt                = " [%a, %d %b %Y]"
    masthead_url           = None
    cover_url              = None
    browser_type           = "mechanize"
    resolve_internal_links = False
    recursions             = 0
    compress_news_images   = False
    compress_news_images_max_size = None
    ignore_duplicate_articles = None
    recipe_specific_options = None

    def __init__(self):
        self.log    = CalibreLog()
        self._br    = None
        self._cutoff = datetime.now(utc_tz) - timedelta(days=self.oldest_article)
        # Flatten recipe_specific_options to a plain {key: default} dict
        rso = self.__class__.recipe_specific_options
        if rso and isinstance(rso, dict):
            defaults = {}
            for k, meta in rso.items():
                if isinstance(meta, dict) and 'default' in meta:
                    defaults[k] = meta['default']
            self.recipe_specific_options = defaults
        else:
            self.recipe_specific_options = {}

    # ---- browser ----

    def get_browser(self, *args, **kwargs):
        ua = kwargs.pop('user_agent', None)
        if self._br is None or ua is not None:
            # Create a new browser (or replace it) when a specific UA is requested.
            # This matches calibre behaviour: the economist recipe calls
            # get_browser(user_agent=X) on retry to force a new UA.
            self._br = Browser(user_agent=ua or DEFAULT_UA)
        return self._br

    get_browser.is_base_class_implementation = True

    def clone_browser(self, br):
        return br.clone_browser()

    @property
    def browser(self):
        return self.get_browser()

    @browser.setter
    def browser(self, br):
        self._br = br

    # ---- feed list ----

    def get_feeds(self):
        return self.feeds

    # ---- URL hooks ----

    def get_article_url(self, article):
        return getattr(article, 'link', None) or article.get('url', '')

    def print_version(self, url):
        return url

    def canonicalize_internal_url(self, url, is_link=True):
        from urllib.parse import urlparse
        p = urlparse(url)
        return p.netloc + p.path

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
        return None

    # ---- abort helpers ----

    def abort_article(self, msg='abort'):
        raise AbortArticle(msg)

    def abort_recipe_processing(self, msg='abort'):
        raise RuntimeError(f"Recipe aborted: {msg}")

    # ---- utilities ----

    def index_to_soup(self, url_or_html, raw=False):
        if url_or_html.lstrip().startswith('<'):
            html = url_or_html
        else:
            br = self.get_browser()
            resp = br.open(url_or_html)
            # Raise here so recipes get a clear HTTPError they can catch —
            # but only for hard failures (5xx). For 4xx the recipe's own
            # try/except handles the logic (e.g. economist re-tries with
            # a different UA on 403).
            if resp.status_code >= 500:
                resp.raise_for_status()
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
        pass

    def cleanup(self):
        pass

    def get_extra_css(self):
        return self.extra_css or ''

    def get_cover_url(self):
        return getattr(self, 'cover_url', None)

    def get_masthead_url(self):
        return getattr(self, 'masthead_url', None)

    def get_url_specific_delay(self, url):
        return self.delay

    def is_link_wanted(self, url, tag):
        return True

    def _is_article_old(self, pub_date_str):
        if not pub_date_str:
            return False
        try:
            from dateutil.parser import parse as _p
            dt = _p(str(pub_date_str))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=utc_tz)
            return dt < self._cutoff
        except Exception:
            return False

# ---------------------------------------------------------------------------
# Plugin stubs
# ---------------------------------------------------------------------------

class Plugin:
    name = 'Plugin'
    description = ''
    version = (1, 0, 0)
    author = ''

class FileTypePlugin(Plugin):
    file_types = set()
    on_import = False
    on_postimport = False

# ---------------------------------------------------------------------------
# polyglot shims
# ---------------------------------------------------------------------------

def _build_polyglot():
    poly         = types.ModuleType('polyglot')
    poly_func    = types.ModuleType('polyglot.functools')
    poly_builtin = types.ModuleType('polyglot.builtins')
    poly_urllib  = types.ModuleType('polyglot.urllib')
    poly_http    = types.ModuleType('polyglot.http_client')
    poly_queue   = types.ModuleType('polyglot.queue')

    poly_func.lru_cache          = lru_cache
    poly_builtin.as_bytes        = lambda s, enc='utf-8': s.encode(enc) if isinstance(s, str) else s
    poly_builtin.as_unicode      = force_unicode
    poly_builtin.iteritems       = lambda d: d.items()
    poly_builtin.itervalues      = lambda d: d.values()
    poly_builtin.iterkeys        = lambda d: d.keys()
    poly_builtin.string_or_bytes = (str, bytes)
    poly_builtin.unicode_type    = str
    poly_builtin.map             = map
    poly_builtin.filter          = filter
    poly_builtin.zip             = zip
    poly_builtin.range           = range
    poly_builtin.print_function  = print

    import urllib.parse, urllib.request, urllib.error
    poly_urllib.parse      = urllib.parse
    poly_urllib.request    = urllib.request
    poly_urllib.error      = urllib.error
    poly_urllib.quote      = urllib.parse.quote
    poly_urllib.quote_plus = urllib.parse.quote_plus
    poly_urllib.unquote    = urllib.parse.unquote
    poly_urllib.urlencode  = urllib.parse.urlencode
    poly_urllib.urlopen    = urllib.request.urlopen

    import http.client
    poly_http.HTTPException = http.client.HTTPException

    import queue
    poly_queue.Queue = queue.Queue
    poly_queue.Empty = queue.Empty

    for m in (poly, poly_func, poly_builtin, poly_urllib, poly_http, poly_queue):
        sys.modules[m.__name__] = m

# ---------------------------------------------------------------------------
# mechanize shim
# ---------------------------------------------------------------------------

def _build_mechanize_shim():
    try:
        import mechanize as _mech
        # Real mechanize is installed – just make sure it's in sys.modules
        sys.modules.setdefault('mechanize', _mech)
        return
    except ImportError:
        pass

    mech = types.ModuleType('mechanize')

    class Request:
        def __init__(self, url, data=None, headers=None):
            self._url = url
            self.data = data
            self.headers = dict(headers or {})
        def get_full_url(self):
            return self._url
        def add_header(self, key, val):
            self.headers[key] = val
        def add_unredirected_header(self, key, val):
            self.headers[key] = val

    mech.Request = Request
    sys.modules['mechanize'] = mech

# ---------------------------------------------------------------------------
# html5_parser shim
# ---------------------------------------------------------------------------

def _build_html5_parser_shim():
    try:
        import html5_parser  # noqa: already installed
        return
    except ImportError:
        pass

    h5 = types.ModuleType('html5_parser')

    def parse(html, treebuilder='lxml', namespaceHTMLElements=False, **kw):
        """
        Substitute for html5_parser.parse() using lxml.
        The economist recipe calls this as:
          root = parse(raw)   → then root.xpath('//script[@id="__NEXT_DATA__"]')
          root = parse(html)  → then etree.tostring(root, encoding='unicode')
        Must return an lxml _Element, not an ElementTree.
        """
        from lxml import etree
        from lxml.html import fromstring as html_fromstring
        try:
            if isinstance(html, str):
                html = html.encode('utf-8')
            # html_fromstring returns an HtmlElement (subclass of _Element)
            # which supports both .xpath() and etree.tostring()
            return html_fromstring(html)
        except Exception:
            try:
                # Fallback: parse as generic XML
                return etree.fromstring(html)
            except Exception:
                return etree.Element('html')

    h5.parse = parse
    sys.modules['html5_parser'] = h5

# ---------------------------------------------------------------------------
# Main install() – wire everything into sys.modules
# ---------------------------------------------------------------------------

def install():
    """Inject all calibre stubs. Safe to call multiple times."""
    if 'calibre' in sys.modules:
        return

    def _stub(name):
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    # core calibre
    calibre = _stub('calibre')
    calibre.browser                = browser
    calibre.strftime               = strftime
    calibre.random_user_agent      = random_user_agent
    calibre.preferred_encoding     = 'utf-8'
    calibre.force_unicode          = force_unicode
    calibre.as_unicode             = as_unicode
    calibre.prepare_string_for_xml = prepare_string_for_xml
    calibre.iswindows              = False
    calibre.ismacos                = False
    calibre.islinux                = True
    calibre.__appname__            = 'calibre'
    calibre.prints                 = print
    calibre.calibre_most_common_ua = DEFAULT_UA

    # calibre.web.feeds.news + .recipes alias
    _stub('calibre.web')
    _stub('calibre.web.feeds')
    news = _stub('calibre.web.feeds.news')
    news.BasicNewsRecipe  = BasicNewsRecipe
    news.classes          = classes
    news.prefixed_classes = prefixed_classes
    news.NoArticles       = NoArticles
    ra = _stub('calibre.web.feeds.recipes')
    ra.BasicNewsRecipe  = BasicNewsRecipe
    ra.classes          = classes
    ra.prefixed_classes = prefixed_classes
    ra.NoArticles       = NoArticles

    # calibre.ebooks.*
    _stub('calibre.ebooks')
    bs = _stub('calibre.ebooks.BeautifulSoup')
    bs.BeautifulSoup   = BeautifulSoup
    bs.NavigableString = NavigableString
    bs.Tag             = Tag
    bs.CData           = CData
    _stub('calibre.ebooks.oeb')
    _stub('calibre.ebooks.metadata')
    opf = _stub('calibre.ebooks.metadata.opf2')
    class _OPFCreator:
        def __init__(self, *a, **kw): pass
    opf.OPFCreator = _OPFCreator

    # calibre.browser
    brmod = _stub('calibre.browser')
    brmod.Browser = Browser
    brmod.browser = browser

    # calibre.ptempfile
    ptmp = _stub('calibre.ptempfile')
    ptmp.PersistentTemporaryFile = PersistentTemporaryFile
    ptmp.TemporaryDirectory      = tempfile.TemporaryDirectory
    ptmp.TemporaryFile           = tempfile.TemporaryFile
    ptmp.NamedTemporaryFile      = tempfile.NamedTemporaryFile

    # calibre.utils.*
    _stub('calibre.utils')

    date = _stub('calibre.utils.date')
    date.local_tz        = local_tz
    date.utc_tz          = utc_tz
    date.parse_date      = parse_date
    date.strptime        = strptime
    date.parse_only_date = parse_only_date
    date.strftime        = strftime
    date.isoformat       = isoformat
    date.now             = now
    date.UNDEFINED_DATE  = datetime(101, 1, 1, tzinfo=utc_tz)

    logm = _stub('calibre.utils.logging')
    logm.Log       = CalibreLog
    logm.GUILog    = CalibreLog
    logm.ANSIStream = CalibreLog

    rua = _stub('calibre.utils.random_ua')
    rua.common_english_word_ua          = common_english_word_ua
    rua.random_common_chrome_user_agent = random_common_chrome_user_agent

    clean = _stub('calibre.utils.cleantext')
    clean.clean_ascii_chars = clean_ascii_chars
    clean.clean_xml_chars   = clean_ascii_chars

    img = _stub('calibre.utils.img')
    img.scale_image     = lambda *a, **kw: b''
    img.image_from_data = lambda *a, **kw: None

    iso = _stub('calibre.utils.iso8601')
    iso.local_tz      = local_tz
    iso.utc_tz        = utc_tz
    iso.parse_iso8601 = parse_date   # alias — same semantics

    _stub('calibre.utils.formatter_functions')
    _stub('calibre.utils.config')

    # calibre.customize
    cust = _stub('calibre.customize')
    cust.Plugin         = Plugin
    cust.FileTypePlugin = FileTypePlugin

    # polyglot, mechanize, html5_parser
    _build_polyglot()
    _build_mechanize_shim()
    _build_html5_parser_shim()
