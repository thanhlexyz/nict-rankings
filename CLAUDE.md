# CLAUDE.md: how to operate and maintain this site

A Hugo site (English) that lists the citations of NICT researchers from **OpenAlex only** (maintainer's decision of
2026-10-10: Google Scholar is not used), counting papers on which OpenAlex prints the person with an NICT affiliation,
and groups papers by SCImago journal quartile and CORE conference rank at the time of the paper.
Layout follows `../vn-at-top-ai-conference`: `backend/` (Python, writes `frontend/data/`) and `frontend/` (Hugo, own layouts).

## Cycle

1. Edit the hand-kept files (below) or code.
2. `make data` (no network) then `make build` (no warnings) and `make test`.
3. Look at the numbers that moved; take headless screenshots (`chromium --headless --screenshot`, served with
   `python3 -m http.server` from `frontend/public`), light and dark.

## Hand-kept files (`backend/`)

| file | what it holds |
|---|---|
| `roster.csv` | everyone tracked: `row` (workbook row, or `x1`... for people added later), `slug`, `name`, `name_ja`, `aliases` (`;`), `scholar_id`, `researchmap_id`, `orcid`, `homepage`, `openalex_ids` (`;`), `approved`, `notes`. Edit with Python `csv`, never `sed`. `read_xlsx.py` re-reads the workbook and keeps hand edits. |
| `self_reported.csv` | papers read from a person's own page (`slug,title,authors,venue,year,state,source_url,note`): unofficial confirmation. A paper already on the profile is confirmed (and takes the page's venue); one missing from it is added, counted, tagged `self_reported`. |
| `paper_overrides.csv` | `slug,key,decision,note`: `yes` counts a paper, `no` leaves it out, with the reason. |
| `venue_overrides.csv` | `venue,kind,quartile,core_rank,note`: fix a venue string the matcher gets wrong. |
| `scholar.json` | snapshot per person (the file name is historical: it holds the OpenAlex paper lists the site uses, and older Scholar, Researchmap, ORCID snapshots). Written by the fetch scripts only. |
| `history.csv`, `xlsx_history.csv` | the monthly series: own snapshots, and the workbook's sheets. |

`raw/` and `work/` are git-ignored caches. `work/build_report.txt` lists what needs a human.

## Counting rules (the About page states them; keep both in sync)

- A person's papers are all works of their OpenAlex author ID(s), whatever affiliation is printed (`fetch_openalex_people.py`): being at
  NICT is not required, being the right person is. IDs confirmed in `roster.csv` `openalex_ids` (an ORCID gives one: `fetch_openalex.py
  --resolve`) are used as they are; otherwise the IDs are provisional: those OpenAlex put on NICT-printed authorships matching the person's name,
  and only works whose printed name matches are kept. Provisional people are listed on the Issues page with each ID's profile: confirm the IDs.
  Citations are OpenAlex's `cited_by_count`; per-year figures are `counts_by_year` (last ten years).
- Not applied, by the maintainer's choice: self-citations and co-author/same-lab citations stay counted.
- `period_from` / `period_to` in `roster.csv` limit a person's counted papers to those years (unused by default).
- `self_reported.csv` papers (a person's own page) are added with no citation figure, tagged unofficial.
- Wording is facts only. Names are of real colleagues; do not publish without the maintainer's go-ahead (`local = true` in `hugo.toml`).
- Journals: SCImago best quartile, by ISSN then exact title; not found = "not in SCImago". Conferences: CORE at the time of the paper:
  the newest edition earlier than the paper's year (`venues.edition_order`), then older, then later editions (2014, 2017, 2018, 2020,
  2021, 2023, ICORE2026; `make rankings`). Not found = unranked; Australasian/national ranks count as unranked.
- Class order: Conf. A* > Journal Q1 > Conf. A > Journal Q2 > Conf. B > the rest (`CLASS_RANK` in `build_site_data.py`).
- Since 2021: "received since" = per-year citations 2021 on; "papers since" = published 2021 on, with their own citations and h.
- Yearly page: per-person and group bars of OpenAlex `counts_by_year` (last ten years); the current year is marked partial. No monthly view (it showed no trend);
  `fetch_monthly.py` is kept but not run. The workbook's Scholar totals are not used (maintainer: its bookkeeping is wrong).
- Snapshots of other sources stay in `scholar.json` but are not built unless added to `common.ACTIVE_SOURCES`.

## Scholar cleaned (the calibrated calculation)

- `profile_check.py`: cleaned citations = Scholar citations of the profile's articles whose author list names the person (cut lists completed
  from the paper page; initial-and-surname matching; a roster `topic_regex` sets aside same-name papers outside the person's field).
  Calibrated on the maintainer's own profile (Thanh Le): 19 articles, all name him, 121 citations, h 8, exactly Scholar's totals.
- `make`-less driver `backend/work/scholar_all.sh`: all profiles via `SCHOLAR_VIA_SSH=corsair`, waits out HTTP 429 (30 min) and resumes, then
  `import_preprints.py --from-checks` (named preprint articles OpenAlex lacks, counted, unofficial) and the build.
  Reading Scholar by script is against Google's terms; the maintainer asked for it. Keep it slow and low-volume.

## Network etiquette

- OpenAlex: the key comes from the environment (`OPENALEX_API_KEY`), is never printed or stored, and no `mailto` is sent. The free
  budget is small: the scripts stop at the budget error (`OpenAlexBudget`) and keep what they have.
- `make snapshot` never runs from `make data`.

## Common requests

**"Track `<person>`."** Add a roster row (name, aliases for other romanisations, optional `orcid`), then `fetch_openalex.py --resolve --only <slug>`
(an ORCID gives the author ID directly; otherwise confirm a candidate from `work/openalex_candidates.csv`), `fetch_openalex_people.py --only <slug>`,
`make data`. A name only in kanji needs a Latin alias.

**A paper is wrongly left out / counted.** Add a row to `paper_overrides.csv` with a dated note (`yes` counts it, `no` leaves it out); for a name spelling, add an alias to `roster.csv`.
