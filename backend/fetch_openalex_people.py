#!/usr/bin/env python3
"""The site's source: all OpenAlex works of the right person, whatever the affiliation printed on them.

    python3 fetch_openalex_people.py [--only <slug>] [--all]

Who is "the right person" is an OpenAlex author ID (or several: OpenAlex splits one researcher over profiles):
  1. `openalex_ids` in roster.csv, confirmed by the maintainer (an ORCID gives one directly, see fetch_openalex.py --resolve);
  2. otherwise provisionally the IDs OpenAlex attached, on works printing NICT (institution I90023481), to an authorship whose
     name matches the person. Such a person is flagged on the Issues page until the IDs are confirmed in roster.csv.
Then every work of those IDs is kept; for provisional IDs also only where the authorship's printed name matches, which
drops the works of a namesake that OpenAlex has merged into the profile. The result goes into scholar.json with
`source: openalex`, `author_ids` and `ids_confirmed`; each paper has `nict` (printed with NICT) for information.
"""
import argparse
import collections
import csv
import re
import sys

from common import HISTORY, SCHOLAR, TODAY, OpenAlexBudget, author_matches, h_index, i10_index, load_json, load_roster, save_json
from fetch_openalex import NICT, api

SELECT = "id,doi,title,publication_year,type,cited_by_count,counts_by_year,authorships,primary_location,primary_topic"


def short(i):
    return (i or "").rsplit("/", 1)[-1]


def has_nict(a):
    return any(short(i["id"]) == NICT or NICT in "".join(i.get("lineage", [])) for i in a.get("institutions", []))


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


def observed_ids(p):
    """Author IDs OpenAlex put on NICT-printed authorships whose name matches the person: {id: works}."""
    seen = collections.Counter()
    for form in forms(p):
        cursor = "*"
        while cursor:
            r = api("works", filter=f'authorships.institutions.lineage:{NICT},raw_author_name.search:"{form}"', select="id,authorships",
                    **{"per-page": 100, "cursor": cursor})
            for w in r["results"]:
                for a in w["authorships"]:
                    aid = short((a.get("author") or {}).get("id"))
                    if aid and has_nict(a) and author_matches(a.get("raw_author_name") or a["author"].get("display_name") or "", p["names"]):
                        seen[aid] += 1
            cursor = r["meta"].get("next_cursor") if r["results"] else None
    return seen


def works_of(ids):
    found = {}
    for chunk in [ids[i:i + 20] for i in range(0, len(ids), 20)]:
        cursor = "*"
        while cursor:
            r = api("works", filter="author.id:" + "|".join(chunk), select=SELECT, **{"per-page": 100, "cursor": cursor})
            for w in r["results"]:
                found[w["id"]] = w
            cursor = r["meta"].get("next_cursor") if r["results"] else None
    return list(found.values())


def profiles(ids):
    out = []
    for chunk in [ids[i:i + 40] for i in range(0, len(ids), 40)]:
        r = api("authors", filter="ids.openalex:" + "|".join(chunk), select="id,display_name,works_count,cited_by_count,affiliations",
                **{"per-page": 50})
        for a in r["results"]:
            out.append({"id": short(a["id"]), "name": a["display_name"], "works": a["works_count"], "cited_by": a["cited_by_count"],
                        "institutions": [i["institution"]["display_name"] for i in a.get("affiliations", [])[:3] if i.get("institution")]})
    return out


def to_paper(w, ids):
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    mine = [a for a in w["authorships"] if short((a.get("author") or {}).get("id")) in ids]
    return {
        "key": "oa" + short(w["id"]), "title": w.get("title") or "",
        "authors": ", ".join((a.get("author") or {}).get("display_name") or "" for a in w["authorships"] if a.get("author")),
        "authors_cut": False, "venue": src.get("display_name") or "", "year": w.get("publication_year"),
        "cites": w.get("cited_by_count", 0), "doi": (w.get("doi") or "").replace("https://doi.org/", "").lower(),
        "issn": src.get("issn") or [], "rm_type": "international_conference_proceedings" if src.get("type") == "conference" else "",
        "openalex": short(w["id"]), "nict": any(has_nict(a) for a in mine),
        # everyone on the paper: OpenAlex author ID, printed name, first institution and its country (for the cooperation page)
        "coauthors": [{"id": short((a.get("author") or {}).get("id")), "name": (a.get("author") or {}).get("display_name") or "",
                       "inst": ((a.get("institutions") or [{}])[0].get("display_name") or ""),
                       "country": ((a.get("institutions") or [{}])[0].get("country_code") or "")}
                      for a in w["authorships"] if a.get("author")],
        "topics": " ".join(filter(None, [(w.get("primary_topic") or {}).get("display_name"),
                                         ((w.get("primary_topic") or {}).get("subfield") or {}).get("display_name"),
                                         ((w.get("primary_topic") or {}).get("field") or {}).get("display_name")])),
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
        if re.search(r"not found \(maintainer", p["notes"], re.I):
            continue  # the maintainer treats this person as not found in OpenAlex
        have = load_json(SCHOLAR, {}).get(p["slug"])
        if have and have.get("source") == "openalex" and have.get("scope") == "all" and not a.all and not a.only:
            continue
        confirmed = bool(p["openalex_ids"])
        ids = list(p["openalex_ids"])
        dropped = []
        if not confirmed:
            seen = observed_ids(p)
            cand = list(seen)
            works_n = {pr["id"]: pr["works"] for pr in profiles(cand)} if cand else {}
            # an ID OpenAlex attached to one or two NICT works but whose profile is mostly elsewhere is a namesake's
            ids = [i for i, n in seen.most_common() if n >= 3 or (works_n.get(i) and n / works_n[i] >= 0.2)]
            dropped = [f"{i} ({seen[i]} NICT works of {works_n.get(i, '?')})" for i in cand if i not in ids]
            if dropped:
                print(f"  {p['slug']}: dropped weakly linked IDs: {', '.join(dropped)}", file=sys.stderr)
        if not ids:
            print(f"  {p['slug']}: no OpenAlex author ID for {forms(p)}", file=sys.stderr)
            continue
        works = works_of(ids)
        papers = []
        for w in works:
            if not confirmed:  # provisional IDs: keep only authorships whose printed name is the person's
                if not any(short((x.get("author") or {}).get("id")) in ids and
                           author_matches(x.get("raw_author_name") or (x.get("author") or {}).get("display_name") or "", p["names"])
                           for x in w["authorships"]):
                    continue
            papers.append(to_paper(w, set(ids)))
        papers = [x for x in papers if x["title"]]
        # a person whose OpenAlex profile is merged with a namesake's can be limited to their field (roster `topic_regex`, matched
        # on the title and OpenAlex's topic names); works printed with NICT are always kept
        rx = re.compile(p["topic_regex"], re.I) if p.get("topic_regex") else None
        if rx:
            before = len(papers)
            papers = [x for x in papers if x["nict"] or rx.search(x["title"] + " " + x.get("topics", ""))]
            print(f"  {p['slug']}: topic filter kept {len(papers)} of {before}", file=sys.stderr)
        years = collections.Counter()
        for x in papers:
            for y, c in x["by_year"].items():
                years[y] += c
        counts = [x["cites"] for x in papers]
        data = load_json(SCHOLAR, {})
        data[p["slug"]] = {
            "source": "openalex", "scope": "all", "author_ids": ids, "ids_confirmed": confirmed, "dropped_ids": dropped, "author_profiles": profiles(ids),
            "user": "", "url": f"https://openalex.org/authors/{ids[0]}", "name": p["name"], "affiliation": "", "email": "",
            "citations": sum(counts), "citations_since": sum(c for y, c in years.items() if int(y) >= 2021), "h_index": h_index(counts),
            "h_index_since": 0, "i10_index": i10_index(counts), "i10_index_since": 0, "since": 2021,
            "by_year": dict(sorted(years.items())), "papers": papers, "fetched": TODAY.isoformat(),
        }
        save_json(SCHOLAR, data)
        fresh = not HISTORY.exists()
        with HISTORY.open("a", encoding="utf-8", newline="") as hf:
            w = csv.writer(hf)
            if fresh:
                w.writerow(["date", "slug", "citations", "h_index", "i10_index", "citations_since", "h_index_since", "i10_index_since", "papers"])
            w.writerow([TODAY.isoformat(), p["slug"], sum(counts), h_index(counts), i10_index(counts), data[p["slug"]]["citations_since"], 0, 0, len(papers)])
        n_nict = sum(1 for x in papers if x["nict"])
        print(f"  {p['slug']}: {len(papers)} papers ({n_nict} printed with NICT) by {len(ids)} author ID(s)"
              f"{'' if confirmed else ' [provisional]'}, cited {sum(counts)}, h {h_index(counts)}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except OpenAlexBudget as e:
        sys.exit(str(e))
