#!/usr/bin/env python3
"""Add the papers of a person's own Scholar profile that OpenAlex lacks to self_reported.csv (unofficial, own profile).

    SCHOLAR_VIA_SSH=corsair python3 import_scholar_papers.py --slug thanh-le

For a person who asks for it: their Scholar profile is the fullest list of their own papers. A paper already in the OpenAlex
snapshot (or already in self_reported.csv) is left alone; each other paper becomes a row with `cites` = Scholar's count.
"""
import argparse
import csv
import sys

from common import SCHOLAR, SELF_REPORTED, load_json, load_roster, title_key
from fetch_scholar import read_profile

FIELDS = ["slug", "title", "authors", "venue", "year", "state", "source_url", "note", "cites"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    a = ap.parse_args()
    p = next(r for r in load_roster() if r["slug"] == a.slug)
    prof = read_profile(p["scholar_id"])
    have = {title_key(x["title"]) for x in load_json(SCHOLAR, {}).get(a.slug, {}).get("papers", [])}
    rows = list(csv.DictReader(SELF_REPORTED.open(encoding="utf-8"))) if SELF_REPORTED.exists() else []
    have |= {title_key(r["title"]) for r in rows if r["slug"] == a.slug}
    url = f"https://scholar.google.com/citations?user={p['scholar_id']}"
    added = 0
    for x in prof["papers"]:
        if title_key(x["title"]) in have or not x["title"]:
            continue
        rows.append({"slug": a.slug, "title": x["title"], "authors": x["authors"], "venue": x["venue"], "year": x["year"] or "",
                     "state": "published", "source_url": url, "cites": x["cites"],
                     "note": "Own Scholar profile of the person (OpenAlex lacks the paper); citations are Scholar's"})
        added += 1
    with SELF_REPORTED.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for r in rows:
            r.setdefault("cites", "")
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print(f"{a.slug}: profile has {len(prof['papers'])} papers, {added} added to {SELF_REPORTED.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
