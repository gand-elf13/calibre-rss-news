IMAGE   ?= calibre-rss
REGISTRY ?= ghcr.io
OWNER   ?= $(or $(GITHUB_REPOSITORY_OWNER),REPO_OWNER)
TAG     ?= latest

# ── Local development ──────────────────────────────────────────────────────────

.PHONY: install
install:
	pip install -r requirements.txt

.PHONY: install-dev
install-dev:
	pip install ruff 2>/dev/null || pip install --break-system-packages ruff 2>/dev/null || echo "Install ruff manually: pipx install ruff"

.PHONY: lint
lint:
	ruff check .
	ruff format --check .

.PHONY: fmt
fmt:
	ruff check --fix .
	ruff format .

.PHONY: test
test:
	@recipe=$$(ls recipes/*.recipe 2>/dev/null | head -1); \
	if [ -n "$$recipe" ]; then \
		python calibre_rss.py --test "$$recipe"; \
	else \
		echo "No recipes found — drop a .recipe file in recipes/"; \
	fi

.PHONY: list
list:
	python calibre_rss.py --list recipes/

.PHONY: run
run:
	python calibre_rss.py recipes/

.PHONY: clean
clean:
	rm -rf feeds/*.xml __pycache__ .ruff_cache

# ── Docker ─────────────────────────────────────────────────────────────────────

.PHONY: docker-build
docker-build:
	docker build -t $(IMAGE) .

.PHONY: docker-run
docker-run:
	docker run --rm \
		-v $(PWD)/recipes:/app/recipes:ro \
		-v $(PWD)/feeds:/app/feeds \
		$(IMAGE) python calibre_rss.py /app/recipes

.PHONY: docker-compose-up
docker-compose-up:
	docker compose up -d

.PHONY: docker-compose-down
docker-compose-down:
	docker compose down

.PHONY: docker-tag
docker-tag:
	docker tag $(IMAGE) $(REGISTRY)/$(OWNER)/calibre-rss:$(TAG)

.PHONY: docker-push
docker-push:
	docker push $(REGISTRY)/$(OWNER)/calibre-rss:$(TAG)

.PHONY: docker-release
docker-release: docker-build docker-tag docker-push
