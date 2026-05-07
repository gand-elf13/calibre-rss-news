# calibre-rss

[![status](https://ci.codeberg.org/api/badges/REPO_OWNER/calibre-rss/status.svg)](https://ci.codeberg.org/REPO_OWNER/calibre-rss)
[![Docker](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fcodeberg.org%2Fapi%2Fv1%2Fpackages%2FREPO_OWNER%2Fcalibre-rss&query=%24.packages%5B%3F%40.type%3D%3D%27container%27%5D.version&style=flat&logo=docker&label=image&color=2496ED)](https://codeberg.org/REPO_OWNER/calibre-rss/-/packages/container/calibre-rss/latest)

Run Calibre `.recipe` files **without Calibre installed** and output standard
**Atom RSS feeds** (`.xml`) that any feed reader can consume.

## What it does

1. Loads any `.recipe` file from a folder you maintain
2. Emulates the full `calibre.web.feeds.news.BasicNewsRecipe` API
3. Fetches & cleans article HTML (respecting `keep_only_tags`, `remove_tags`,
   `auto_cleanup`, `preprocess_html`, `preprocess_regexps`, etc.)
4. Writes one `<name>.xml` Atom feed per recipe into an output directory
5. Run it on a cron / systemd timer / Docker to keep feeds up to date

---

## Quick start

```bash
# Native
pip install -r requirements.txt
python calibre_rss.py recipes/

# Docker (one-shot)
docker run --rm \
  -v ./recipes:/app/recipes:ro \
  -v ./feeds:/app/feeds \
  ghcr.io/REPO_OWNER/calibre-rss

# Docker (scheduled — runs every hour)
docker compose up -d
```

---

## Docker

### Pre-built image

Pull from [GitHub Container Registry](https://ghcr.io):

```bash
docker pull ghcr.io/REPO_OWNER/calibre-rss:latest
```

### Build locally

```bash
docker build -t calibre-rss .
```

### Run modes

**One-shot** (for cron/systemd host scheduling):

```bash
docker run --rm \
  -v ./recipes:/app/recipes:ro \
  -v ./feeds:/app/feeds \
  calibre-rss python calibre_rss.py /app/recipes
```

**Scheduled loop** (container stays up, updates periodically):

```bash
docker run -d --restart unless-stopped \
  -v ./recipes:/app/recipes:ro \
  -v ./feeds:/app/feeds \
  -e RUN_INTERVAL=3600 \
  calibre-rss
```

**With docker-compose** (recommended):

```yaml
services:
  calibre-rss:
    build: .
    container_name: calibre-rss
    restart: unless-stopped
    volumes:
      - ./recipes:/app/recipes:ro
      - ./feeds:/app/feeds
      - ./cookies:/app/cookies:ro    # optional
    environment:
      - TZ=UTC
      - RUN_INTERVAL=3600
```

```bash
docker compose up -d
```

### Volumes

| Mount | Purpose |
|---|---|
| `./recipes` (ro) | `.recipe` files to process |
| `./feeds` | Generated `.xml` feeds |
| `./cookies` (ro, optional) | Netscape cookie files per recipe |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `RUN_INTERVAL` | `3600` | Seconds between update runs |
| `FLAGS` | *(empty)* | Extra CLI flags (e.g. `--no-content`) |
| `TZ` | `UTC` | Container timezone |

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
├── scheduler.py            # Docker scheduler loop
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── recipes/                # ← drop your .recipe files here
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

---

## Contributing

### Prerequisites

- Python 3.10+
- `pip install -r requirements.txt`

### Development

```bash
# Lint
make lint

# Build Docker image locally
make docker-build

# Test with a single recipe (fast mode)
python calibre_rss.py --test recipes/hacker_news.recipe
```

### Code style

- Uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting
- No trailing whitespace, UTF-8 encoding
- Follow existing patterns in the codebase

### Pull requests

1. Fork the repository
2. Create a feature branch
3. Run `make lint` before committing
4. Open a PR against the `main` branch

---

## License

See [LICENSE](LICENSE).

[recipes]: https://github.com/kovidgoyal/calibre/tree/master/recipes
