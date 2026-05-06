# calibre-rss

Run Calibre `.recipe` files **without Calibre installed** and output standard
**Atom RSS feeds** (`.xml`) that any feed reader can consume.

## What it does

1. Loads any `.recipe` file from a folder you maintain
2. Emulates the full `calibre.web.feeds.news.BasicNewsRecipe` API
3. Fetches & cleans article HTML (respecting `keep_only_tags`, `remove_tags`,
   `auto_cleanup`, `preprocess_html`, `preprocess_regexps`, etc.)
4. Writes one `<name>.xml` Atom feed per recipe into an output directory
5. Run it on a cron / systemd timer to keep feeds up to date

---

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Run all recipes in recipes/ → writes feeds/*.xml
python calibre_rss.py recipes/

# Single recipe
python calibre_rss.py recipes/hacker_news.recipe

# Custom output dir
python calibre_rss.py -o /var/www/html/feeds recipes/

# Test mode (1 feed, 2 articles, fast)
python calibre_rss.py --test recipes/hacker_news.recipe

# Skip full-article fetch (feed summary only, much faster)
python calibre_rss.py --no-content recipes/

# List available recipes without running
python calibre_rss.py --list recipes/
```

---

## Project layout

```
calibre-rss/
├── calibre_rss.py          # CLI entry point
├── calibre_compat/
│   └── __init__.py         # Calibre module stubs (calibre.web.feeds.news etc.)
├── recipe_loader.py        # Dynamically loads .recipe files
├── runner.py               # Executes a recipe: feed parsing + article fetching
├── fetcher.py              # HTTP fetch + HTML cleaning per recipe rules
├── rss_writer.py           # Atom XML feed generator
├── requirements.txt
├── recipes/                # ← put your .recipe files here
│   ├── hacker_news.recipe
│   └── lobsters.recipe
└── feeds/                  # ← generated .xml feeds end up here (git-ignore this)
```

---

## Supported recipe features

| Feature | Supported |
|---|---|
| `feeds = [(title, url), ...]` | ✅ |
| `get_feeds()` override | ✅ |
| `parse_index()` override | ✅ |
| `oldest_article` cutoff | ✅ |
| `max_articles_per_feed` | ✅ |
| `keep_only_tags` | ✅ |
| `remove_tags` | ✅ |
| `remove_tags_before` / `_after` | ✅ |
| `preprocess_regexps` | ✅ |
| `preprocess_html(soup)` hook | ✅ |
| `postprocess_html(soup)` hook | ✅ |
| `preprocess_raw_html(html, url)` | ✅ |
| `print_version(url)` | ✅ |
| `get_article_url(article)` | ✅ |
| `auto_cleanup` (readability) | ✅ |
| `use_embedded_content` | ✅ |
| `no_stylesheets` | ✅ |
| `remove_javascript` | ✅ |
| `classes()` helper | ✅ |
| `index_to_soup(url)` | ✅ |
| `tag_to_string(tag)` | ✅ |
| `Browser` / `get_browser()` | ✅ stub |
| `needs_subscription` login | ⚠️ basic stub |
| Simultaneous downloads | ✅ ThreadPoolExecutor |
| Kindle masthead / cover | ➖ ignored |

---

## Writing your own recipes

Calibre recipes are plain Python files (`.recipe` extension = `.py`). Any
recipe from [Calibre's built-in collection][recipes] works directly — just
drop the file into your `recipes/` folder.

**Minimal recipe:**
```python
from calibre.web.feeds.news import BasicNewsRecipe

class MySource(BasicNewsRecipe):
    title          = 'My News Source'
    oldest_article = 3          # days
    max_articles_per_feed = 20
    auto_cleanup   = True       # readability-based extraction
    language       = 'en'

    feeds = [
        ('Section A', 'https://example.com/feed/section-a.rss'),
        ('Section B', 'https://example.com/feed/section-b.rss'),
    ]
```

**With fine-grained HTML cleaning:**
```python
from calibre.web.feeds.news import BasicNewsRecipe, classes

class MySource(BasicNewsRecipe):
    title = 'My Source'
    oldest_article = 7
    max_articles_per_feed = 15

    keep_only_tags = [
        classes('article-content', 'post-body'),
        dict(name='article'),
    ]
    remove_tags = [
        dict(name='div', attrs={'class': ['ad', 'related', 'sidebar']}),
        dict(name='aside'),
    ]

    feeds = [('Main', 'https://example.com/rss')]
```

**With custom article list (no RSS feed):**
```python
from calibre.web.feeds.news import BasicNewsRecipe

class MySource(BasicNewsRecipe):
    title = 'My Source'

    def parse_index(self):
        soup = self.index_to_soup('https://example.com/archive')
        articles = []
        for a in soup.select('h2.headline a'):
            articles.append({
                'title': self.tag_to_string(a),
                'url':   a['href'],
                'date':  '',
            })
        return [('All articles', articles)]
```

---

## Running on a schedule

**cron** (every 6 hours):
```cron
0 */6 * * * cd /path/to/calibre-rss && python calibre_rss.py -q recipes/
```

**systemd timer** (`~/.config/systemd/user/calibre-rss.service`):
```ini
[Unit]
Description=Update Calibre RSS feeds

[Service]
Type=oneshot
WorkingDirectory=/path/to/calibre-rss
ExecStart=/usr/bin/python3 calibre_rss.py -q recipes/
```

```ini
# calibre-rss.timer
[Unit]
Description=Run calibre-rss every 6 hours

[Timer]
OnBootSec=5min
OnUnitActiveSec=6h

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now calibre-rss.timer
```

---

## Serving the feeds

The generated `.xml` files are static — serve them with any web server or
file server:

```bash
# Quick local test
python -m http.server 8080 --directory feeds/
# → http://localhost:8080/hacker_news.xml
```

With **nginx**:
```nginx
location /feeds/ {
    alias /path/to/calibre-rss/feeds/;
    types { application/atom+xml xml; }
    add_header Cache-Control "public, max-age=1800";
}
```

[recipes]: https://github.com/kovidgoyal/calibre/tree/master/recipes
