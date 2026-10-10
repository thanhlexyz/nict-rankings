#!/usr/bin/env python3
"""Identity check: which OpenAlex author is the person a Scholar profile belongs to?

    SCHOLAR_VIA_SSH=corsair python3 scholar_identity.py [--only <slug>] [--write] [--titles 25]

Scholar is not a source of the site's figures. A profile the maintainer names is an anchor for *who* the person is: the
paper titles on it are looked up in OpenAlex (exact title, year within one) and the author ID printed on the person's name
is counted. IDs found on at least two titles (or on the only titles found) are the person's; --write puts them in
roster.csv `openalex_ids` (confirmed by the maintainer's profile) and records the evidence in work/identity.json.
"""
import argparse
import collections
import csv
import sys
import time
import re

from common import ROSTER, WORK, OpenAlexBudget, author_matches, load_json, load_roster, save_json, title_key
from fetch_openalex import api
from fetch_scholar import read_profile
from fetch_researchmap import curl_json, pick


def ids_for(title, year, names):
    r = api("works", filter="title.search:" + re.sub(r"[,:|()\[\]\"'?*<>]", " ", title)[:200], select="id,title,publication_year,authorships",
            **{"per-page": 5})
    out = []
    for w in r.get("results", []):
        if title_key(w.get("title") or "") != title_key(title):
            continue
        if year and w.get("publication_year") and abs(w["publication_year"] - year) > 1:
            continue
        for a in w["authorships"]:
            au = a.get("author") or {}
            if au.get("id") and author_matches(a.get("raw_author_name") or au.get("display_name") or "", names):
                out.append(au["id"].rsplit("/", 1)[-1])
    return out


def researchmap_titles(rm):
    """Title, year and cites=0 of the papers a Researchmap record lists (published papers and misc), de-duplicated."""
    out, seen = [], set()
    for ep in ("published_papers", "misc"):
        start = 1
        while True:
            r = curl_json(f"https://api.researchmap.jp/{rm}/{ep}?limit=100&start={start}")
            for it in r.get("items", []):
                t = pick(it.get("paper_title") or {})
                k = title_key(t)
                if t and k not in seen:
                    seen.add(k)
                    out.append({"title": t, "year": int(str(it.get("publication_date", ""))[:4] or 0) or None, "cites": 0})
            if start + 100 > r.get("total_items", 0):
                break
            start += 100
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--titles", type=int, default=25)
    ap.add_argument("--redo", action="store_true", help="also people already checked (evidence in work/identity.json)")
    a = ap.parse_args()
    evidence = load_json(WORK / "identity.json", {})
    for p in load_roster():
        if (a.only and p["slug"] != a.only) or not (p["scholar_id"] or p.get("researchmap_id")):
            continue
        if p["slug"] in evidence and evidence[p["slug"]].get("ids") and not a.redo and not a.only:
            continue
        if p["scholar_id"]:
            try:
                prof = read_profile(p["scholar_id"])
            except RuntimeError as e:
                print(f"  {p['slug']}: {e}", file=sys.stderr)
                continue
        elif p.get("researchmap_id"):
            prof = {"papers": researchmap_titles(p["researchmap_id"]), "name": p["name"], "affiliation": "Researchmap"}
        else:
            continue
        if not prof or not prof["papers"]:
            print(f"  {p['slug']}: no anchor titles", file=sys.stderr)
            continue
        papers = sorted(prof["papers"], key=lambda x: -x["cites"])[: a.titles]
        votes, found = collections.Counter(), 0
        for x in papers:
            got = set(ids_for(x["title"], x["year"], p["names"] + [prof["name"]]))
            if got:
                found += 1
                votes.update(got)
        top = max(votes.values(), default=0)
        # an ID needs real support: at least two titles and a quarter of the best ID's (a namesake shares a title or two)
        ids = [i for i, n in votes.most_common() if (n >= 2 and n >= 0.25 * top) or found <= 3]
        evidence[p["slug"]] = {"scholar_name": prof["name"], "scholar_affiliation": prof["affiliation"], "titles_checked": len(papers),
                               "titles_found_in_openalex": found, "votes": dict(votes.most_common()), "ids": ids}
        save_json(WORK / "identity.json", evidence)
        print(f"  {p['slug']} ({prof['name']}): {found}/{len(papers)} titles in OpenAlex; IDs {dict(votes.most_common(4))}", file=sys.stderr)
        if a.write and ids:
            rows = list(csv.DictReader(ROSTER.open(encoding="utf-8")))
            fl = list(rows[0].keys())
            for r in rows:
                if r["slug"] == p["slug"]:  # add to what is there (an ORCID-derived or hand-entered ID is never dropped)
                    r["openalex_ids"] = ";".join(dict.fromkeys([*(x for x in r["openalex_ids"].split(";") if x), *ids]))
            with ROSTER.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fl)
                w.writeheader()
                w.writerows(rows)
        time.sleep(8)


if __name__ == "__main__":
    try:
        main()
    except OpenAlexBudget as e:
        sys.exit(str(e))
