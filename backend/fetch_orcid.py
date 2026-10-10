#!/usr/bin/env python3
"""Snapshot for people with an ORCID record and no Scholar profile: works from ORCID, authors and citations from OpenAlex.

    python3 fetch_orcid.py [--only <slug>]

ORCID works carry a title, year, venue and (mostly) a DOI but no author list, so the authors come from the OpenAlex
record found by DOI. A work with no OpenAlex record has no author list and stays "unconfirmed". The result goes into
scholar.json with `source: orcid`.
"""
import argparse
import collections
import subprocess
import sys
import json

from common import SCHOLAR, TODAY, h_index, i10_index, load_json, load_roster, save_json
from fetch_researchmap import openalex_counts

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def orcid_json(orcid, part):
    out = subprocess.run(["curl", "-sL", "--max-time", "60", "-A", UA, "-H", "Accept: application/json",
                          f"https://pub.orcid.org/v3.0/{orcid}/{part}"], capture_output=True).stdout
    return json.loads(out.decode("utf-8", "ignore"))


def works(orcid):
    """One paper per ORCID group (ORCID already merges duplicates of the same work)."""
    out = []
    for g in orcid_json(orcid, "works").get("group", []):
        w = g["work-summary"][0]
        ids = {i["external-id-type"]: i["external-id-value"] for i in g["external-ids"]["external-id"]}
        year = ((w.get("publication-date") or {}).get("year") or {}).get("value")
        doi = (ids.get("doi") or "").lower().replace("https://doi.org/", "")
        out.append({
            "key": f"orcid{w['put-code']}", "title": w["title"]["title"]["value"], "authors": "", "authors_cut": False,
            "venue": ((w.get("journal-title") or {}).get("value") or "").strip(),
            "year": int(year) if year else None, "cites": 0, "doi": doi, "issn": [],
            "rm_type": {"conference-paper": "international_conference_proceedings", "journal-article": "scientific_journal"}.get(w.get("type"), w.get("type") or ""),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    for p in load_roster():
        if not p.get("orcid") or (a.only and p["slug"] != a.only):
            continue
        papers = works(p["orcid"])
        openalex_counts(papers)
        years = collections.Counter()
        for x in papers:
            for y, c in x.get("by_year", {}).items():
                years[y] += c
        counts = [x["cites"] for x in papers]
        data = load_json(SCHOLAR, {})
        data[p["slug"]] = {
            "source": "orcid", "user": p["orcid"], "url": f"https://orcid.org/{p['orcid']}", "name": p["name"],
            "affiliation": "", "email": "", "citations": sum(counts),
            "citations_since": sum(c for y, c in years.items() if int(y) >= 2021), "h_index": h_index(counts), "h_index_since": 0,
            "i10_index": i10_index(counts), "i10_index_since": 0, "since": 2021,
            "by_year": dict(sorted(years.items())), "papers": papers, "fetched": TODAY.isoformat(),
        }
        save_json(SCHOLAR, data)
        hit = sum(1 for x in papers if x.get("openalex"))
        print(f"  {p['slug']}: {len(papers)} works, {hit} found in OpenAlex, cited {sum(counts)}, h {h_index(counts)}", file=sys.stderr)


if __name__ == "__main__":
    from common import OpenAlexBudget
    try:
        main()
    except OpenAlexBudget as e:
        sys.exit(str(e))
