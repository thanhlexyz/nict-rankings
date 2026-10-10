#!/usr/bin/env python3
"""Snapshot for people with no Scholar profile: the paper list from Researchmap, citations from OpenAlex.

    python3 fetch_researchmap.py [--only <slug>]

Researchmap (researchmap.jp, JST) lists a researcher's papers with complete author lists, DOIs and ISSNs but no
citation counts, so each paper's count comes from OpenAlex (by DOI, then by exact title). The result goes into
scholar.json in the same shape as a Scholar snapshot, with `source: researchmap`, so the build treats both alike.
There is no profile total to compare against, so such a person has no "claimed" figure.
"""
import argparse
import collections
import json
import re
import subprocess
import sys
import time
import urllib.parse

from common import (SCHOLAR, TODAY, OpenAlexBudget, budget_check, h_index, i10_index, load_json, load_roster, save_json,
                    title_key, with_key)

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def curl_json(url):
    for i in range(3):
        out = subprocess.run(["curl", "-sL", "--max-time", "60", "-A", UA, "-H", "Accept: application/json", with_key(url)],
                             capture_output=True).stdout
        try:
            return budget_check(json.loads(out.decode("utf-8", "ignore")))
        except ValueError:  # rate limit page, timeout, or an unsupported title query: retry, then give up on this lookup
            time.sleep(3 * (i + 1))
    return {}


def pick(d, *langs):
    """{'en': ..., 'ja': ...} -> the English form, else Japanese."""
    if not isinstance(d, dict):
        return d or ""
    for k in (*langs, "en", "ja"):
        if d.get(k):
            return d[k]
    return next(iter(d.values()), "")


def read_papers(rm):
    items, start = [], 1
    while True:
        r = curl_json(f"https://api.researchmap.jp/{rm}/published_papers?limit=100&start={start}")
        items += r.get("items", [])
        if len(items) >= r.get("total_items", 0) or not r.get("items"):
            return items
        start += 100
        time.sleep(1)


def paper_of(it):
    authors = it.get("authors") or {}
    names = [a.get("name", "") for a in (authors.get("en") or authors.get("ja") or [])]
    ids = it.get("identifiers") or {}
    venue = pick(it.get("publication_name"))
    if it.get("volume"):
        venue += f" {it['volume']}" + (f" ({it['number']})" if it.get("number") else "")
    return {
        "key": f"rm{it.get('rm:id')}", "title": pick(it.get("paper_title")), "authors": ", ".join(n for n in names if n),
        "authors_cut": False, "venue": venue.strip(), "year": int(str(it.get("publication_date", ""))[:4] or 0) or None,
        "cites": 0, "doi": (ids.get("doi") or [""])[0].lower(), "issn": ids.get("issn") or [],
        "rm_type": it.get("published_paper_type", ""),
    }


def openalex_counts(papers):
    by_doi = {p["doi"]: p for p in papers if p["doi"]}
    dois = list(by_doi)
    found = {}
    for i in range(0, len(dois), 40):
        chunk = dois[i:i + 40]
        q = urllib.parse.urlencode({"filter": "doi:" + "|".join("https://doi.org/" + d for d in chunk), "per-page": 100,
                                    "select": "id,doi,title,cited_by_count,counts_by_year,authorships"}, safe=":,|/")
        for w in curl_json(f"https://api.openalex.org/works?{q}").get("results", []):
            found[(w.get("doi") or "").replace("https://doi.org/", "").lower()] = w
        time.sleep(0.2)
    for p in papers:
        w = found.get(p["doi"])
        if not w and len(title_key(p["title"])) > 15:  # no DOI, or not indexed under it: exact title
            q = urllib.parse.urlencode({"filter": "title.search:" + re.sub(r"[,:]", " ", p["title"])[:200], "per-page": 5,
                                        "select": "id,doi,title,cited_by_count,counts_by_year,publication_year,authorships"}, safe=":,|/")
            for c in curl_json(f"https://api.openalex.org/works?{q}").get("results", []):
                if title_key(c.get("title") or "") == title_key(p["title"]) and abs((c.get("publication_year") or 0) - (p["year"] or 0)) <= 1:
                    w = c
                    break
            time.sleep(0.2)
        if w:
            p["cites"] = w.get("cited_by_count", 0)
            p["by_year"] = {str(c["year"]): c["cited_by_count"] for c in w.get("counts_by_year", [])}
            p["openalex"] = w["id"].rsplit("/", 1)[-1]
            if not p["authors"]:  # ORCID lists no authors: take them from the OpenAlex record
                p["authors"] = ", ".join(a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author"))
                p["authors_from"] = "OpenAlex"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    data = load_json(SCHOLAR, {})
    for p in load_roster():
        if not p.get("researchmap_id") or (a.only and p["slug"] != a.only):
            continue
        rm = p["researchmap_id"]
        profile = curl_json(f"https://api.researchmap.jp/{rm}")
        papers = [paper_of(i) for i in read_papers(rm)]
        papers = [x for x in papers if x["title"]]
        if not papers:
            print(f"  {p['slug']}: Researchmap lists no papers; snapshot left as it is", file=sys.stderr)
            continue
        openalex_counts(papers)
        years = collections.Counter()
        for x in papers:
            for y, c in x.get("by_year", {}).items():
                years[y] += c
        counts = [x["cites"] for x in papers]
        since = sum(c for y, c in years.items() if int(y) >= 2021)
        name = " ".join(filter(None, [pick(profile.get("given_name")), pick(profile.get("family_name"))])) or p["name"]
        data[p["slug"]] = {
            "source": "researchmap", "user": rm, "url": f"https://researchmap.jp/{rm}", "name": name, "affiliation": "",
            "email": "", "citations": sum(counts), "citations_since": since, "h_index": h_index(counts), "h_index_since": 0,
            "i10_index": i10_index(counts), "i10_index_since": 0, "since": 2021,
            "by_year": dict(sorted(years.items())), "papers": papers, "fetched": TODAY.isoformat(),
        }
        hit = sum(1 for x in papers if x.get("openalex"))
        print(f"  {p['slug']}: {len(papers)} papers, {hit} found in OpenAlex, cited {sum(counts)}, h {h_index(counts)}", file=sys.stderr)
    save_json(SCHOLAR, data)


if __name__ == "__main__":
    try:
        main()
    except OpenAlexBudget as e:
        sys.exit(str(e))
