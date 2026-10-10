#!/bin/sh
# Manual snapshot, in order, one network job at a time (Scholar blocks parallel requests):
# queued IDs -> Scholar profiles -> Researchmap and ORCID people -> OpenAlex-only people -> OpenAlex records -> build.
# The OpenAlex stages need OPENALEX_API_KEY (or a day with budget left); they stop with a message otherwise.
cd "$(dirname "$0")" || exit 1
python3 add_profile.py --pending
python3 fetch_scholar.py --skip-fetched --details
python3 fetch_researchmap.py
python3 fetch_orcid.py
python3 fetch_openalex_people.py
python3 fetch_openalex.py --resolve
python3 fetch_openalex.py
python3 build_site_data.py
