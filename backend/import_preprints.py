#!/usr/bin/env python3
"""Preprints on a person's Scholar profile that OpenAlex lacks, with Scholar's citation counts, into scholar_preprints.csv.

    SCHOLAR_VIA_SSH=corsair python3 import_preprints.py [--only <slug>]

A preprint (arXiv, SSRN, TechRxiv, Research Square, HAL, OSF, bioRxiv, ...) counts. OpenAlex often has the published version
only, or the arXiv record without the profile's citations, so the profile's entries are added where the OpenAlex snapshot has no
paper of that title. The author list must name the person (a cut list is completed from the paper page). Rows are unofficial
and tagged; `cites` are Scholar's. The file is regenerated per person: rows of the person are replaced on each run.
"""
import argparse
import csv
import re
import sys
import time

from common import BACKEND, SCHOLAR, rebuild_site, authors_include, fold, load_json, load_roster, split_authors, title_key
from fetch_scholar import DETAIL_DELAY, DELAY, read_details, read_profile

OUT = BACKEND / "scholar_preprints.csv"
FIELDS = ["slug", "title", "authors", "venue", "year", "state", "source_url", "note", "cites"]
PREPRINT = re.compile(r"arxiv|preprint|ssrn|techrxiv|researchsquare|research square|biorxiv|medrxiv|chemrxiv|hal\b|osf\b|openreview|authorea|zenodo", re.I)


def jaccard(a, b):
    a, b = set(a.split()), set(b.split())
    return len(a & b) / len(a | b) if a | b else 0


def from_checks():
    """No Scholar request: the preprints among the already-read, named articles of profile_checks.json."""
    import json
    checks = json.load(open(BACKEND / "profile_checks.json"))
    snaps = load_json(SCHOLAR, {})
    out = []
    for slug, c in checks.items():
        have_keys = {title_key(x["title"]) for x in snaps.get(slug, {}).get("papers", [])}
        have = [fold(x["title"]) for x in snaps.get(slug, {}).get("papers", [])]
        for r in c["rows"]:
            if r["status"] != "named" or not PREPRINT.search(r["venue"] or ""):
                continue
            if title_key(r["title"]) in have_keys or any(jaccard(fold(r["title"]), h) >= 0.8 for h in have):
                continue
            out.append({"slug": slug, "title": r["title"], "authors": r["authors"], "venue": r["venue"], "year": r["year"] or "",
                        "state": "preprint", "cites": r["cites"], "source_url": c["scholar_url"],
                        "note": "Preprint on the person's Scholar profile; not in OpenAlex; citations are Scholar's"})
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(out)
    rebuild_site()
    print(f"{len(out)} preprints from {len(checks)} checked profiles, {sum(int(r['cites']) for r in out)} citations", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--from-checks", action="store_true")
    a = ap.parse_args()
    if a.from_checks:
        return from_checks()
    snaps = load_json(SCHOLAR, {})
    rows = list(csv.DictReader(OUT.open(encoding="utf-8"))) if OUT.exists() else []
    for p in load_roster():
        if (a.only and p["slug"] != a.only) or not p["scholar_id"]:
            continue
        try:
            prof = read_profile(p["scholar_id"])
        except RuntimeError as e:
            print(f"  stopped at {p['slug']}: {e}", file=sys.stderr)
            break
        if not prof:
            continue
        have = [fold(x["title"]) for x in snaps.get(p["slug"], {}).get("papers", [])]
        have_keys = {title_key(x["title"]) for x in snaps.get(p["slug"], {}).get("papers", [])}
        names = p["names"] + [prof["name"]]
        mine, seen = [], 0
        for x in prof["papers"]:
            if not PREPRINT.search(x["venue"] or ""):
                continue
            seen += 1
            if title_key(x["title"]) in have_keys or any(jaccard(fold(x["title"]), h) >= 0.8 for h in have):
                continue
            named = authors_include(split_authors(x["authors"]), names)
            if not named and x["authors_cut"]:
                try:
                    full = read_details(p["scholar_id"], x)
                    if full:
                        x["authors"] = full
                        named = authors_include(split_authors(full), names)
                except RuntimeError:
                    pass
                time.sleep(DETAIL_DELAY)
            if not named:
                continue
            mine.append({"slug": p["slug"], "title": x["title"], "authors": x["authors"], "venue": x["venue"], "year": x["year"] or "",
                         "state": "preprint", "cites": x["cites"],
                         "source_url": f"https://scholar.google.com/citations?user={p['scholar_id']}",
                         "note": "Preprint on the person's Scholar profile; not in OpenAlex; citations are Scholar's"})
        rows = [r for r in rows if r["slug"] != p["slug"]] + mine
        with OUT.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"  {p['slug']}: {seen} preprints on the profile, {len(mine)} added ({sum(int(m['cites']) for m in mine)} citations)", file=sys.stderr)
        time.sleep(DELAY)


if __name__ == "__main__":
    main()
