# runner.py – execute a loaded recipe and collect article data

import logging
import concurrent.futures
from datetime import datetime, timezone

import feedparser
import requests

from fetcher import fetch_article
from calibre_compat import AbortArticle

logger = logging.getLogger("runner")


def _article_identifier(art, keys):
    """Compute a dedup identifier tuple from an article dict for the given keys.
    Returns None if any required key is missing."""
    parts = []
    for key in keys:
        val = art.get(key)
        if not val:
            return None
        parts.append(str(val))
    return tuple(parts)


DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _make_session(recipe):
    """Return the requests.Session from the recipe's browser shim."""
    br = recipe.get_browser()
    # Our Browser shim has ._session; fall back to a plain session
    session = getattr(br, '_session', None)
    if session is None or not isinstance(session, requests.Session):
        session = requests.Session()
        session.headers['User-Agent'] = DEFAULT_UA
    return session


def _parse_feed_entry(entry):
    """Extract a normalised article dict from a feedparser entry."""
    url = entry.get('link', '')
    title = entry.get('title', '(no title)')
    description = ''
    for key in ('summary', 'content', 'description'):
        val = entry.get(key)
        if val:
            if isinstance(val, list):
                val = val[0].get('value', '')
            description = val
            break

    pub_date = entry.get('published') or entry.get('updated') or ''
    author = ''
    if entry.get('author'):
        author = entry['author']
    elif entry.get('author_detail', {}).get('name'):
        author = entry['author_detail']['name']

    return {
        'title': title,
        'url': url,
        'description': description,
        'pub_date': pub_date,
        'author': author,
        'content_html': None,
    }


def _feeds_from_recipe(recipe):
    """
    Return [(feed_title, [article_dict, ...]), ...]
    Honours both get_feeds() and parse_index().
    """
    # parse_index() takes priority if overridden
    # Wrap recipe.log so all internal self.log() calls surface at DEBUG level
    orig_log = recipe.log
    class TracingLog(type(orig_log)):
        def __call__(self, *args):
            logger.debug("  [recipe.log] " + " ".join(str(a) for a in args))
        def info(self, *args):
            logger.debug("  [recipe.log] " + " ".join(str(a) for a in args))
        def warn(self, *args):
            logger.warning("  [recipe.log.warn] " + " ".join(str(a) for a in args))
        def warning(self, *args):
            logger.warning("  [recipe.log.warn] " + " ".join(str(a) for a in args))
        def error(self, *args):
            logger.error("  [recipe.log.error] " + " ".join(str(a) for a in args))
        def debug(self, *args):
            logger.debug("  [recipe.log.debug] " + " ".join(str(a) for a in args))
        def exception(self, *args):
            import traceback, sys
            msg = " ".join(str(a) for a in args)
            exc = sys.exc_info()
            if exc[0] is not None:
                tb = "".join(traceback.format_exception(*exc))
                logger.error(f"  [recipe.log.exception] {msg}\n{tb}")
            else:
                logger.error(f"  [recipe.log.exception] {msg}")
    recipe.log = TracingLog()
    try:
        pi = recipe.parse_index()
    except Exception as e:
        # NoArticles (and similar recipe-defined sentinels) mean the recipe
        # ran successfully but found nothing — treat as empty, not a crash.
        from calibre_compat import NoArticles
        if isinstance(e, NoArticles) or type(e).__name__ == 'NoArticles':
            logger.warning(f"Recipe reported no articles: {e}")
            return []
        raise
    if pi is not None:
        if not pi:
            logger.debug("parse_index() returned empty list — recipe found no sections/articles")
        else:
            total = sum(len(arts) for _, arts in pi)
            logger.debug(f"parse_index() returned {len(pi)} feed(s), {total} article(s)")
        return pi  # recipe already returns [(title, [articles])]

    raw_feeds = recipe.get_feeds()
    if not raw_feeds:
        return []

    result = []
    for feed_spec in raw_feeds:
        if isinstance(feed_spec, (list, tuple)) and len(feed_spec) == 2:
            feed_title, feed_url = feed_spec
        else:
            feed_url = str(feed_spec)
            feed_title = ''

        logger.info(f"Parsing feed: {feed_url}")
        try:
            parsed = feedparser.parse(feed_url, agent=DEFAULT_UA)
        except Exception as e:
            logger.warning(f"feedparser error on {feed_url}: {e}")
            continue

        if not feed_title:
            feed_title = parsed.feed.get('title', feed_url)

        articles = []
        for entry in parsed.entries[:recipe.max_articles_per_feed]:
            art = _parse_feed_entry(entry)
            # honour oldest_article cutoff
            if recipe._is_article_old(art['pub_date']):
                logger.debug(f"Skipping old article: {art['title']}")
                continue
            # embedded content shortcut
            if recipe.use_embedded_content is True or (
                recipe.use_embedded_content is None
                and art['description']
                and len(art['description']) > 200
            ):
                art['content_html'] = art['description']
            articles.append(art)

        result.append((feed_title, articles))

    return result


def _fetch_one(art, recipe, session):
    """Fetch and clean article content; returns article dict."""
    url = recipe.get_article_url(
        type('_FeedEntry', (), {'link': art['url'], 'get': lambda self, k, d='': art.get(k, d)})()
    ) or art['url']

    if not url:
        return art

    if art.get('content_html'):
        return art

    logger.info(f"  Fetching: {url}")
    content_html, _final_url = fetch_article(url, recipe, session=session)
    if content_html:
        art['content_html'] = content_html
        # Keep the original article URL — don't overwrite with a
        # file:/// temp path that print_version() may have returned.
    recipe.postprocess_article(art, url)
    return art


def run_recipe(recipe, max_workers=None, existing_ids=None):
    """
    Execute the recipe.
    Returns list of article dicts:
        {title, url, content_html, pub_date, author, description, feed_title}

    existing_ids : set[str] | None
        URLs already present in the persisted feed — articles whose URL
        matches are skipped (cross-run deduplication).
    """
    workers = max_workers or min(recipe.simultaneous_downloads, 8)
    session = _make_session(recipe)

    feeds_data = _feeds_from_recipe(recipe)

    # Cross-run dedup: track URLs already in the persisted feed
    seen_urls = set(existing_ids) if existing_ids else set()
    # Within-run dedup: honour recipe-level setting (standard calibre feature)
    dedup_keys = getattr(recipe, 'ignore_duplicate_articles', None)
    within_run_seen = set() if dedup_keys is not None else None

    all_articles = []

    for feed_title, articles in feeds_data:
        if not articles and recipe.remove_empty_feeds:
            continue

        to_fetch = []
        for art in articles:
            art['feed_title'] = feed_title

            # Cross-run dedup: skip if URL already exists in the persisted feed
            url = art.get('url')
            if url and url in seen_urls:
                logger.debug(f"Skipping article already in feed: {art['title']}")
                continue
            if url:
                seen_urls.add(url)

            # Within-run dedup: same article appearing in multiple sections
            if within_run_seen is not None:
                ident = _article_identifier(art, dedup_keys)
                if ident is not None:
                    if ident in within_run_seen:
                        logger.debug(f"Skipping within-run duplicate: {art['title']}")
                        continue
                    within_run_seen.add(ident)

            if not art.get('content_html'):
                to_fetch.append(art)
            else:
                all_articles.append(art)

        if to_fetch:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {
                    ex.submit(_fetch_one, art, recipe, None): art
                    for art in to_fetch
                }
                ARTICLE_TIMEOUT = 60  # seconds per article before giving up
                for fut in concurrent.futures.as_completed(futures, timeout=None):
                    orig = futures[fut]
                    try:
                        result = fut.result(timeout=ARTICLE_TIMEOUT)
                        all_articles.append(result)
                    except concurrent.futures.TimeoutError:
                        logger.warning(f"Timed out fetching {orig.get('url', '?')}, skipping")
                        all_articles.append(orig)
                    except AbortArticle:
                        pass
                    except Exception as e:
                        logger.warning(f"Error processing {orig.get('url', '?')}: {e}")
                        all_articles.append(orig)  # include with no content

    recipe.cleanup()
    return all_articles
