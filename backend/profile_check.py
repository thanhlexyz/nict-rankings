#!/usr/bin/env python3
"""Clean a Scholar profile: which of its citations are on papers that are really the person's.

    SCHOLAR_VIA_SSH=corsair python3 profile_check.py --slug <slug>          # one person
    SCHOLAR_VIA_SSH=corsair python3 profile_check.py --all [--redo]        # everyone with a Scholar ID, stops at the first 429
    python3 profile_check.py --slug <slug> --from-html saved_profile.html  # offline, from a saved profile page
    python3 profile_check.py --slug <slug> --rescore                       # new topic filter on the saved rows

The calculation (calibrated on the maintainer's own profile, where it reproduces Scholar's own 121 citations, h 8):
  1. read every article of the profile with its author list; complete a cut list from the paper page;
  2. an article is the person's when its author list names them (initial-and-surname matching, kanji too);
  3. for a person with a roster `topic_regex` (a common name), an article that names them but lies outside that field
     is set aside as "same name, outside the field";
  4. cleaned citations = the Scholar citations of the articles that remain; h and i10 are recomputed from them.
Writes profile_checks.json (all rows kept, with their status), then builds the site data.
"""
import argparse
import re
import subprocess
import sys
import time

from common import BACKEND, TODAY, rebuild_site, authors_include, h_index, i10_index, load_json, load_roster, save_json, split_authors
from fetch_scholar import DELAY, DETAIL_DELAY, parse_header, parse_papers, read_details, read_profile

OUT = BACKEND / "profile_checks.json"


def score(p, prof, url, detail=True):
    rx = re.compile(p["topic_regex"], re.I) if p.get("topic_regex") else None
    names = p["names"] + [prof["name"]]
    rows = []
    for x in prof["papers"]:
        named = authors_include(split_authors(x["authors"]), names)
        if x["authors_cut"] and not named and detail:
            full = read_details(p["scholar_id"], x)   # RuntimeError (HTTP 429) propagates: the caller stops
            if full:
                x["authors"], x["authors_cut"] = full, False
                named = authors_include(split_authors(full), names)
            time.sleep(DETAIL_DELAY)
        st = "named" if named else ("unknown" if x["authors_cut"] else "not_named")
        rows.append({"title": x["title"], "year": x["year"], "cites": x["cites"], "authors": x["authors"], "venue": x["venue"], "status": st})
    return summarise(p, prof, url, rows, rx)


def summarise(p, prof, url, rows, rx):
    if rx:
        for r in rows:
            if r["status"] == "named" and not rx.search(r["title"] + " " + r["venue"]):
                r["status"] = "named_off_field"
    mine = [r["cites"] for r in rows if r["status"] == "named"]
    cs = lambda s: sum(r["cites"] for r in rows if r["status"] == s)
    n = lambda s: sum(1 for r in rows if r["status"] == s)
    return {
        # Scholar's headline total counts a citing paper once even when it cites several of the person's articles, while the
        # per-article counts add up each time: the cleaned total is scaled so it never exceeds the headline
        "cleaned": (round(sum(mine) * prof["citations"] / sum(r["cites"] for r in rows))
                    if rows and sum(r["cites"] for r in rows) > prof["citations"] else sum(mine)),
        "fetched": TODAY.isoformat(), "scholar_name": prof["name"], "scholar_url": url, "claimed": prof["citations"], "papers": len(rows),
        "papers_sum": sum(r["cites"] for r in rows), "named_papers": len(mine), "named_cites": sum(mine), "named_h": h_index(mine),
        "named_i10": i10_index(mine), "not_named_papers": n("not_named"), "not_named_cites": cs("not_named"),
        "unknown_papers": n("unknown"), "unknown_cites": cs("unknown"), "off_field_papers": n("named_off_field"),
        "off_field_cites": cs("named_off_field"), "topic_regex": p.get("topic_regex", ""), "claimed_h": prof["h_index"],
        "claimed_i10": prof["i10_index"], "rows": sorted(rows, key=lambda r: -r["cites"]),
    }


def say(slug, o):
    print(f"  {slug}: claimed {o['claimed']} | cleaned {o['cleaned']} ({o['named_papers']} papers, h {o['named_h']}) | "
          f"same name, off field {o['off_field_cites']} | not named {o['not_named_cites']} | unknown {o['unknown_cites']}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--rescore", action="store_true")
    ap.add_argument("--from-html")
    a = ap.parse_args()
    out = load_json(OUT, {})
    people = {r["slug"]: r for r in load_roster()}
    todo = ([s for s in out if s in people] if a.rescore and not a.slug else [s for s, r in people.items() if r["scholar_id"]]) if (a.all or (a.rescore and not a.slug)) else [a.slug]
    for slug in todo:
        p = people[slug]
        if a.all and not a.redo and slug in out and out[slug].get("fetched") == TODAY.isoformat():
            continue
        if a.rescore:
            old = out[slug]
            prof = {"name": old["scholar_name"], "citations": old["claimed"], "h_index": old["claimed_h"], "i10_index": old["claimed_i10"]}
            names = p["names"] + [old["scholar_name"]]
            rows = []
            for r in old["rows"]:
                st = "named" if r["status"] == "named_off_field" else r["status"]
                if st == "not_named" and authors_include(split_authors(r["authors"]), names):
                    st = "named"                    # the name matcher improved (middle names): re-judged from the saved author list
                rows.append({**r, "status": st})
            out[slug] = summarise(p, prof, old["scholar_url"], rows, re.compile(p["topic_regex"], re.I) if p.get("topic_regex") else None)
        elif a.from_html:
            h = open(a.from_html, encoding="utf-8").read()
            prof = {**parse_header(h), "papers": parse_papers(h)}
            out[slug] = score(p, prof, f"https://scholar.google.com/citations?user={p['scholar_id']}", detail=False)
        else:
            try:
                prof = read_profile(p["scholar_id"])
                if not prof:
                    continue
                out[slug] = score(p, prof, f"https://scholar.google.com/citations?user={p['scholar_id']}")
            except RuntimeError as e:
                print(f"  stopped at {slug}: {e}", file=sys.stderr)
                sys.exit(3)  # blocked: the caller waits and resumes (done people are skipped)
            time.sleep(DELAY)
        cur = load_json(OUT, {})      # another run may have written meanwhile: merge, never overwrite
        cur[slug] = out[slug]
        out = cur
        save_json(OUT, out)
        say(slug, out[slug])
        if not a.rescore:
            rebuild_site()  # the site shows each person as soon as they are done (a rescore rebuilds once, at the end)


if __name__ == "__main__":
    main()
    if "--rescore" in sys.argv:
        rebuild_site()
