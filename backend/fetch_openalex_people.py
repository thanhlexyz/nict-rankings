#!/usr/bin/env python3
"""OpenAlex-only snapshot: the papers on which the person is printed with an NICT affiliation.

    python3 fetch_openalex_people.py [--only <slug>] [--all]

For every roster person who has no snapshot yet (or none with papers; --all redoes everyone not on Scholar), search
OpenAlex works whose authorship lists NICT (institution I90023481, sub-units included) and a raw author name that
matches one of the person's name forms. Selecting by affiliated authorship, not by author ID, copes with the several
conflated author profiles OpenAlex keeps for one Japanese researcher. A paper counts once per work. The result goes
into scholar.json with `source: openalex`; a later Scholar snapshot replaces it. No profile total exists, so the
person has no "claimed" figure.

Limits: a namesake at NICT would be merged in; names in kanji only are not searchable here.
"""
import argparse
import collections
import sys

from common import SCHOLAR, TODAY, author_matches, h_index, i10_index, load_json, load_roster, save_json
from fetch_openalex import NICT, api

SELECT = "id,doi,title,publication_year,type,cited_by_count,counts_by_year,authorships,primary_location"


def forms(p):
    out = []
    for n in p["names"]:
        if not n.isascii():
            continue
        out.append(n)
        t = n.split()
        if len(t) == 2:
            out.append(f"{t[1]} {t[0]}")
    return list(dict.fromkeys(out))


def search(p):
    found = {}
    for form in forms(p):
        cursor = "*"
        while cursor:
            r = api("works", filter=f'authorships.institutions.lineage:{NICT},raw_author_name.search:"{form}"', select=SELECT,
                    **{"per-page": 100, "cursor": cursor})
            for w in r["results"]:
                mine = [a for a in w["authorships"]
                        if any(i["id"].rsplit("/", 1)[-1] == NICT or "I90023481" in "".join(i.get("lineage", []))
                               for i in a.get("institutions", []))
                        and author_matches(a.get("raw_author_name") or a["author"]["display_name"], p["names"])]
                if mine:
                    found[w["id"]] = w
            cursor = r["meta"].get("next_cursor") if r["results"] else None
    return list(found.values())


def to_paper(w):
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    return {
        "key": "oa" + w["id"].rsplit("/", 1)[-1], "title": w.get("title") or "",
        "authors": ", ".join(a["author"]["display_name"] for a in w["authorships"] if a.get("author")),
        "authors_cut": False, "venue": src.get("display_name") or "", "year": w.get("publication_year"),
        "cites": w.get("cited_by_count", 0), "doi": (w.get("doi") or "").replace("https://doi.org/", "").lower(),
        "issn": src.get("issn") or [], "rm_type": "international_conference_proceedings" if src.get("type") == "conference" else "",
        "openalex": w["id"].rsplit("/", 1)[-1],
        "by_year": {str(c["year"]): c["cited_by_count"] for c in w.get("counts_by_year", [])},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    for p in load_roster():
        if a.only and p["slug"] != a.only:
            continue
        have = load_json(SCHOLAR, {}).get(p["slug"])
        if have and not a.only and (have.get("papers") and (have.get("source", "scholar") != "openalex" or not a.all)):
            continue
        papers = [to_paper(w) for w in search(p)]
        papers = [x for x in papers if x["title"]]
        if not papers:
            print(f"  {p['slug']}: nothing found for {forms(p)}", file=sys.stderr)
            continue
        years = collections.Counter()
        for x in papers:
            for y, c in x["by_year"].items():
                years[y] += c
        counts = [x["cites"] for x in papers]
        data = load_json(SCHOLAR, {})
        data[p["slug"]] = {
            "source": "openalex", "user": "", "url": "https://openalex.org/works?filter=authorships.institutions.lineage:" + NICT,
            "name": p["name"], "affiliation": "NICT (OpenAlex authorship)", "email": "", "citations": sum(counts),
            "citations_since": sum(c for y, c in years.items() if int(y) >= 2021), "h_index": h_index(counts), "h_index_since": 0,
            "i10_index": i10_index(counts), "i10_index_since": 0, "since": 2021, "by_year": dict(sorted(years.items())),
            "papers": papers, "fetched": TODAY.isoformat(),
        }
        save_json(SCHOLAR, data)
        print(f"  {p['slug']}: {len(papers)} papers with an NICT affiliation, cited {sum(counts)}, h {h_index(counts)}", file=sys.stderr)


if __name__ == "__main__":
    from common import OpenAlexBudget
    try:
        main()
    except OpenAlexBudget as e:
        sys.exit(str(e))
