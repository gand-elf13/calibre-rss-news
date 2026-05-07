#!/usr/bin/env python3
"""
calibre-rss – run Calibre .recipe files and generate Atom RSS feeds.

Usage:
    calibre-rss [OPTIONS] [RECIPE ...]

    RECIPE can be:
      - a path to a .recipe file
      - a directory; all *.recipe files inside will be processed

Options:
    -o, --output DIR     Directory to write .xml feed files (default: ./feeds)
    -j, --jobs N         Max parallel article fetches per recipe (default: 5)
    -v, --verbose        Enable verbose logging
    -q, --quiet          Suppress all output except errors
    --no-content         Skip full-article fetch; include only feed summary
    --test               Process only 1 feed / 2 articles per recipe (fast test)
    --list               List available recipes in a directory without running
    -h, --help           Show this help

Examples:
    calibre-rss recipes/                     # run all recipes in folder
    calibre-rss recipes/bbc.recipe           # single recipe
    calibre-rss -o /var/www/feeds recipes/   # custom output dir
    calibre-rss --test recipes/lemonde.recipe
"""

import argparse
import logging
import os
import sys
import glob
from pathlib import Path
from datetime import datetime

# ---- ensure the project root is on sys.path ----
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recipe_loader import load_recipe_file
from runner import run_recipe
from rss_writer import write_atom_feed


def setup_logging(verbose=False, quiet=False):
    level = logging.WARNING if quiet else (logging.DEBUG if verbose else logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(levelname)s  %(name)s  %(message)s',
    )


def collect_recipes(paths):
    """Expand paths (files or dirs) into a list of .recipe file paths."""
    result = []
    for p in paths:
        if os.path.isdir(p):
            result.extend(sorted(glob.glob(os.path.join(p, '**', '*.recipe'), recursive=True)))
        elif os.path.isfile(p) and p.endswith('.recipe'):
            result.append(p)
        else:
            logging.warning(f"Skipping unknown path: {p}")
    return result


def sanitize_filename(name):
    return "".join(c if c.isalnum() or c in '-_.' else '_' for c in name)


def run_one_recipe(recipe_path, output_dir, jobs, no_content, test_mode, cookies_file=None):
    logger = logging.getLogger("calibre-rss")
    logger.info(f"Processing: {recipe_path}")

    try:
        recipe = load_recipe_file(recipe_path)
    except Exception as e:
        logger.error(f"Failed to load {recipe_path}: {e}")
        return False

    if test_mode:
        recipe.test = (1, 2)  # calibre's test tuple: (max_feeds, max_articles)
        recipe.max_articles_per_feed = 2
        if hasattr(recipe, 'feeds') and recipe.feeds:
            recipe.feeds = recipe.feeds[:1]

    if no_content:
        # Monkey-patch to skip article fetching
        recipe.keep_only_tags  = []
        recipe.remove_tags     = []
        recipe.auto_cleanup    = False

    logger.info(f"  Recipe: {recipe.title!r} (oldest_article={recipe.oldest_article}d)")

    # Load cookies if provided (Netscape/Mozilla cookie file format)
    # Also auto-detect cookies/<recipe_stem>.txt alongside the recipe
    cookie_paths = []
    if cookies_file:
        cookie_paths.append(cookies_file)
    auto_cookie = os.path.join(
        os.path.dirname(os.path.abspath(recipe_path)),
        'cookies',
        os.path.splitext(os.path.basename(recipe_path))[0] + '.txt'
    )
    if os.path.exists(auto_cookie) and auto_cookie not in cookie_paths:
        cookie_paths.append(auto_cookie)
        logger.info(f"  Auto-loading cookies: {auto_cookie}")

    if cookie_paths:
        import http.cookiejar
        br = recipe.get_browser()
        for cp in cookie_paths:
            cj = http.cookiejar.MozillaCookieJar()
            try:
                cj.load(cp, ignore_discard=True, ignore_expires=True)
                for cookie in cj:
                    br._session.cookies.set(
                        cookie.name, cookie.value,
                        domain=cookie.domain, path=cookie.path
                    )
                logger.info(f"  Loaded {sum(1 for _ in cj)} cookies from {cp}")
            except Exception as e:
                logger.warning(f"  Failed to load cookies from {cp}: {e}")

    try:
        articles = run_recipe(recipe, max_workers=jobs)
    except Exception as e:
        logger.error(f"Recipe run failed for {recipe_path}: {e}")
        import traceback; traceback.print_exc()
        return False

    if not articles:
        logger.warning(f"  No articles found for {recipe.title!r}")

    # Derive feed URL from recipe (some recipes set cover_url or a homepage)
    feed_url = getattr(recipe, 'INDEX', '') or ''

    xml = write_atom_feed(
        recipe_title=recipe.title,
        recipe_url=feed_url,
        articles=articles,
        description=getattr(recipe, 'description', '') or '',
        language=getattr(recipe, 'language', 'en') or 'en',
    )

    stem = sanitize_filename(Path(recipe_path).stem)
    out_path = os.path.join(output_dir, f"{stem}.xml")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(xml)

    logger.info(f"  ✓ Wrote {len(articles)} articles → {out_path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Run Calibre .recipe files and generate Atom RSS feeds.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('recipes', nargs='*', default=['.'],
                        help='Recipe files or directories (default: current dir)')
    parser.add_argument('-o', '--output', default='feeds',
                        help='Output directory for .xml feeds (default: feeds/)')
    parser.add_argument('-j', '--jobs', type=int, default=5,
                        help='Max parallel fetches per recipe (default: 5)')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-q', '--quiet', action='store_true')
    parser.add_argument('--no-content', action='store_true',
                        help='Skip full-article fetch; use feed summary only')
    parser.add_argument('--test', action='store_true',
                        help='Test mode: only 1 feed / 2 articles per recipe')
    parser.add_argument('--list', action='store_true',
                        help='List recipes without running them')
    parser.add_argument('--cookies', metavar='FILE',
                        help='Netscape cookie file to inject into all recipes. '
                             'Per-recipe cookies are also auto-loaded from '
                             'cookies/<recipe_name>.txt next to the recipe file.')
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, quiet=args.quiet)
    logger = logging.getLogger("calibre-rss")

    recipe_paths = collect_recipes(args.recipes)
    if not recipe_paths:
        print("No .recipe files found.", file=sys.stderr)
        sys.exit(1)

    if args.list:
        for p in recipe_paths:
            print(p)
        return

    ok = fail = 0
    for path in recipe_paths:
        success = run_one_recipe(
            path,
            output_dir=args.output,
            jobs=args.jobs,
            no_content=args.no_content,
            test_mode=args.test,
            cookies_file=getattr(args, 'cookies', None),
        )
        if success:
            ok += 1
        else:
            fail += 1

    if not args.quiet:
        print(f"\nDone: {ok} succeeded, {fail} failed. Feeds written to {args.output}/")

    sys.exit(0 if fail == 0 else 1)


if __name__ == '__main__':
    main()
