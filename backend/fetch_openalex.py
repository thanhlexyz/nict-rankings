#!/usr/bin/env python3
"""OpenAlex records used to confirm that a paper on a Scholar profile names the person as an author.

    python3 fetch_openalex.py --resolve     # propose OpenAlex author IDs (work/openalex_candidates.csv)
    python3 fetch_openalex.py               # works of the confirmed IDs, then title lookups for the rest

`roster.csv: openalex_ids` is hand-kept (`;`-separated). --resolve fills it only where exactly one candidate
has NICT in its affiliations and its name fits; every other person is left for the maintainer, since Japanese
names are heavily conflated in OpenAlex. Everything downloaded goes to raw/openalex.json (a cache).
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from common import (OPENALEX, ROSTER, SCHOLAR, WORK, OpenAlexBudget, author_matches, budget_check, load_json, load_roster,
                    save_json, title_key, with_key, clear_status)

API = "https://api.openalex.org"
NICT = "I90023481"
WORKS_SELECT = "id,doi,title,publication_year,type,cited_by_count,authorships,primary_location,biblio"
DELAY = 0.12


def api(path, **params):
    url = with_key(f"{API}/{path}?" + urllib.parse.urlencode(params, safe=":,|"))
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nict-rankings"}), timeout=60) as r:
                clear_status("openalex_budget")
                time.sleep(DELAY)
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    budget_check(json.loads(e.read().decode("utf-8", "ignore")))
                except ValueError:
                    pass
            if i == 3:
                raise
            time.sleep(5 * (i + 1))
        except Exception as e:  # timeouts: back off
            if i == 3:
                raise
            print(f"  retry {url.split('?')[0]}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))


def slim(w):
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    return {
        "id": w["id"].rsplit("/", 1)[-1], "doi": w.get("doi"), "title": w.get("title") or "",
        "year": w.get("publication_year"), "type": w.get("type"), "cited_by": w.get("cited_by_count", 0),
        "source": src.get("display_name"), "source_type": src.get("type"), "issn": src.get("issn") or [],
        "authors": [{"id": ((a.get("author") or {}).get("id") or "").rsplit("/", 1)[-1],
                     "name": (a.get("author") or {}).get("display_name") or "", "raw": a.get("raw_author_name") or ""}
                    for a in w.get("authorships", [])],
    }


def resolve(people):
    out = []
    roster = list(csv.DictReader(ROSTER.open(encoding="utf-8")))
    for p in people:
        if p["openalex_ids"]:
            continue
        seen = {}
        if p.get("orcid"):  # an ORCID names exactly one OpenAlex author
            r = api("authors", filter="orcid:https://orcid.org/" + p["orcid"]).get("results", [])
            if len(r) == 1:
                aid = r[0]["id"].rsplit("/", 1)[-1]
                for row in roster:
                    if row["slug"] == p["slug"]:
                        row["openalex_ids"] = aid
                print(f"  {p['slug']}: {aid} by ORCID", file=sys.stderr)
                continue
        for name in p["names"]:
            if not name.isascii():
                continue
            for a in api("authors", search=name, **{"per-page": 10}).get("results", []):
                seen[a["id"].rsplit("/", 1)[-1]] = a
        cands = []
        for aid, a in seen.items():
            insts = [i["institution"]["id"].rsplit("/", 1)[-1] for i in a.get("affiliations", []) if i.get("institution")]
            names = [a["display_name"], *(a.get("display_name_alternatives") or [])]
            fits = any(author_matches(n, p["names"]) for n in names)
            cands.append({"slug": p["slug"], "name": p["name"], "openalex_id": aid, "display_name": a["display_name"],
                          "works": a["works_count"], "cited_by": a["cited_by_count"], "nict": NICT in insts, "name_fits": fits,
                          "institutions": "; ".join(i["institution"]["display_name"] for i in a.get("affiliations", [])[:4] if i.get("institution"))})
        out += cands
        good = [c for c in cands if c["nict"] and c["name_fits"]]
        print(f"  {p['slug']}: {len(good)} NICT candidate(s) of {len(cands)}: see work/openalex_candidates.csv (provisional until confirmed)", file=sys.stderr)
    WORK.mkdir(exist_ok=True)
    with (WORK / "openalex_candidates.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["slug", "name", "openalex_id", "display_name", "works", "cited_by", "nict", "name_fits", "institutions"])
        w.writeheader()
        w.writerows(out)
    with ROSTER.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(roster[0].keys()))
        w.writeheader()
        w.writerows(roster)


def fetch_works(aid, cache):
    got, cursor = [], "*"
    while cursor:
        r = api("works", filter=f"author.id:{aid}", select=WORKS_SELECT, **{"per-page": 200, "cursor": cursor})
        got += [slim(w) for w in r["results"]]
        cursor = r["meta"].get("next_cursor") if r["results"] else None
    cache["works_by_author"][aid] = got
    print(f"  {aid}: {len(got)} works", file=sys.stderr)


def lookup_titles(slug, papers, known, cache):
    """Scholar papers with no title match among the person's works: search OpenAlex by title."""
    n = 0
    for p in papers:
        k = title_key(p["title"])
        if len(k) < 12 or k in known or k in cache["titles"]:
            continue
        try:
            r = api("works", filter="title.search:" + re.sub(r"[,:|()\[\]\"'?*<>]", " ", p["title"])[:200], select=WORKS_SELECT,
                    **{"per-page": 5})
        except urllib.error.HTTPError as e:  # one odd title must not stop the run; not cached, so it is retried next time
            print(f"  skipped a title lookup (HTTP {e.code}): {p['title'][:60]!r}", file=sys.stderr)
            continue
        hits = [slim(w) for w in r.get("results", []) if title_key(w.get("title") or "") == k]
        cache["titles"][k] = hits
        n += 1
        if n % 25 == 0:
            save_json(OPENALEX, cache)
    print(f"  {slug}: {n} title lookups", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolve", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    people = [p for p in load_roster() if not a.only or p["slug"] == a.only]
    if a.resolve:
        resolve(people)
        return
    cache = load_json(OPENALEX, {"works_by_author": {}, "titles": {}})
    scholar = load_json(SCHOLAR, {})
    for p in people:
        for aid in p["openalex_ids"]:
            if aid not in cache["works_by_author"]:
                fetch_works(aid, cache)
        known = {title_key(w["title"]) for aid in p["openalex_ids"] for w in cache["works_by_author"].get(aid, [])}
        lookup_titles(p["slug"], scholar.get(p["slug"], {}).get("papers", []), known, cache)
        save_json(OPENALEX, cache)


if __name__ == "__main__":
    try:
        main()
    except OpenAlexBudget as e:
        sys.exit(str(e))
