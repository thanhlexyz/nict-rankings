#!/bin/sh
# OpenAlex-only snapshot: confirm author IDs, fetch each person's NICT-affiliated works, rebuild the site data.
# Needs OPENALEX_API_KEY in the environment (the shared anonymous budget is usually used up); stages stop with a message.
# The Scholar, Researchmap and ORCID fetchers (fetch_scholar.py, fetch_researchmap.py, fetch_orcid.py, add_profile.py)
# are kept but not run: common.ACTIVE_SOURCES = {"openalex"}.
cd "$(dirname "$0")" || exit 1
python3 fetch_openalex.py --resolve
python3 fetch_openalex_people.py --all
python3 build_site_data.py
