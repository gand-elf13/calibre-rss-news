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
└── feeds/                  # ← generated .xml feeds end up here
```

---

## Recipes

Calibre recipes are plain Python files (`.recipe` extension = `.py`). Any
recipe from [Calibre's built-in collection][recipes] works directly — just
drop the file into your `recipes/` folder.

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
