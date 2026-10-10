# Run Python with the environment that has curl-able network and (optionally) networkx; override with PYTHON=...
PYTHON ?= python3

.PHONY: data rankings snapshot build run test clean

data:        ## rebuild frontend/data and the page stubs from the snapshots (no network)
	cd backend && $(PYTHON) build_site_data.py

rankings:    ## download CORE and SCImago tables into backend/raw
	cd backend && $(PYTHON) fetch_rankings.py

snapshot:    ## manual: queued IDs, Scholar, Researchmap, ORCID, OpenAlex, then data. Slow; Scholar throttles.
	cd backend && ./run_pipeline.sh

build: data  ## build the site into frontend/public
	cd frontend && hugo --minify

run: data    ## local server
	cd frontend && hugo server

test:
	cd backend && $(PYTHON) tests/test_core.py

clean:
	rm -rf frontend/public frontend/resources
