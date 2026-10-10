# CLAUDE.md: how to operate and maintain this site

A Hugo site (English) that recounts the Google Scholar citations of NICT researchers, counting only papers
that name the researcher as an author, and groups papers by SCImago journal quartile and CORE conference rank.
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
| `paper_overrides.csv` | `slug,key,decision,note`: `yes` counts a paper, `no` leaves it out, with the reason. |
| `venue_overrides.csv` | `venue,kind,quartile,core_rank,note`: fix a venue string the matcher gets wrong. |
| `scholar.json` | snapshot of every profile and paper list (all sources). Written by the fetch scripts only. |
| `history.csv`, `xlsx_history.csv` | the monthly series: own snapshots, and the workbook's sheets. |

`raw/` and `work/` are git-ignored caches. `work/build_report.txt` lists what needs a human.

## Counting rules (the About page states them; keep both in sync)

- Status per paper (`validate.py`): verified (OpenAlex record names the person), listed (the source's own author
  list names them), unconfirmed (cut or missing author list, no independent record), not_listed (the OpenAlex
  record or a complete list does not name them), maintainer (override). Counted = verified + listed + maintainer.
- Not applied, by the maintainer's choice: self-citations and co-author/same-lab citations stay counted.
- Wording is facts only: "author list does not name the person", never a characterisation or suspicion. Names are of
  real colleagues; do not publish without the maintainer's go-ahead (`local = true` in `hugo.toml` asks crawlers to stay away).
- Journals: SCImago best quartile, by ISSN then exact title; not found = "not in SCImago", never a lower quartile.
  Conferences: CORE (ICORE2026, then CORE2023, CORE2021), by full name or acronym with name overlap; not found = unranked;
  Australasian/national ranks count as unranked. The latest list is applied to every year.
- "Since 2021": Scholar's figure is citations received since 2021; the counted figures are for papers published since
  2021 (Scholar gives no per-paper history). Both are shown.
- People without a Scholar profile: papers from Researchmap (`fetch_researchmap.py`) or ORCID (`fetch_orcid.py`), citations
  and, for ORCID, authors from OpenAlex. They have no "claimed" figure.

## Network etiquette

- Google Scholar answers a Python HTTP client with 429 and throttles the IP after bursts: always `curl`, 8 s apart, details
  pages 6 s apart, and stop at the first block (`add_profile.py --pending` keeps the rest queued). The org page and author
  search need a signed-in browser, so profile IDs are given by hand.
- OpenAlex: no `mailto` is sent. Do not pass the maintainer's e-mail to any service.
- `make snapshot` never runs from `make data`.

## Common requests

**"Track `<Scholar URL>`."** `python3 add_profile.py <url>`: reads the name and affiliation, fills the workbook row with
that name or adds `x<n>`. Then `fetch_scholar.py --only <slug> --details`, `fetch_openalex.py --resolve --only <slug>`
(confirm candidates in `work/openalex_candidates.csv`: name fits and NICT in affiliations), `fetch_openalex.py --only <slug>`, `make data`.

**"Track `<Researchmap URL>`" / ORCID.** `add_profile.py <researchmap url>`; for ORCID add the row by hand with `orcid` and `homepage`,
then `fetch_researchmap.py` / `fetch_orcid.py`.

**A paper is wrongly left out / counted.** Add a row to `paper_overrides.csv` with a dated note; for a name spelling, add an alias to `roster.csv`.
