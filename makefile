PYTHON ?= python3

install:
	sudo pacman -S hugo chromium

# rebuild frontend/data and the page stubs from the snapshots (no network)
data:
	cd backend && $(PYTHON) build_site_data.py

# download the CORE and SCImago tables into backend/raw (cached; delete a file there to refresh)
rankings:
	cd backend && $(PYTHON) fetch_rankings.py

# OpenAlex snapshot: confirm author IDs, fetch each person's works printed with an NICT affiliation, rebuild the data.
# Reads OPENALEX_API_KEY from the environment (never printed or stored); without it the shared anonymous budget is
# usually used up and the stages stop with a message. Run from a shell that has the key (e.g. source your shell profile).
snapshot:
	cd backend && ./run_pipeline.sh

# the workbook again: new rows in the screening list, and the monthly history; hand edits in roster.csv are kept
workbook:
	cd backend && $(PYTHON) read_xlsx.py && $(PYTHON) build_site_data.py

# local server with live reload at http://localhost:1313/ ; rebuilds the data first
run: data
	cd frontend && hugo serve --noHTTPCache --disableFastRender

# the site without a data rebuild, at http://localhost:1313/ (for editing layouts and styles)
serve:
	cd frontend && hugo serve --noHTTPCache --disableFastRender

build: data
	rm -rf frontend/public
	cd frontend && hugo --minify

# Build with frontend/publish.toml laid over hugo.toml and push the result to the gh-pages branch of the origin
# repository (GitHub Pages: Settings > Pages > Deploy from a branch > gh-pages). The site names real colleagues and
# their citation figures, so this refuses to run without CONFIRM=yes: `make publish CONFIRM=yes`.
# The commit is made in a throwaway repository inside frontend/public with this repository's author and a UTC date.
PAGES_REMOTE ?= $(shell git remote get-url origin 2>/dev/null)
GIT_NAME := $(shell git config user.name)
GIT_EMAIL := $(shell git config user.email)

publish: data
	@test "$(CONFIRM)" = yes || { echo "publish makes the page public: run 'make publish CONFIRM=yes' once you have decided"; exit 1; }
	@test -n "$(PAGES_REMOTE)" || { echo "no git remote 'origin': add one, or pass PAGES_REMOTE=<url>"; exit 1; }
	rm -rf frontend/public
	cd frontend && hugo --minify --config hugo.toml,publish.toml
	touch frontend/public/.nojekyll
	cd frontend/public && git init -q -b gh-pages && git add -A \
		&& TZ=UTC git -c user.name="$(GIT_NAME)" -c user.email="$(GIT_EMAIL)" commit -q -m "site of $$(date -u +%F)" \
		&& git push -f $(PAGES_REMOTE) gh-pages
	rm -rf frontend/public/.git

test:
	cd backend && $(PYTHON) tests/test_core.py
	node --check frontend/assets/site.js

clean:
	rm -rf frontend/public frontend/resources backend/work

.PHONY: install data rankings snapshot workbook run serve build publish test clean
