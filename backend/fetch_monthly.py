#!/usr/bin/env python3
"""Citations by month, from OpenAlex: the publication month of the papers that cite each person's papers.

    python3 fetch_monthly.py [--only <slug>]

OpenAlex keeps no citation history by month, but every citing paper has a publication date, so the month a citation
"arrives" is the month its citing paper appeared. A paper citing several of one person's papers is counted once for that
person (distinct citing papers), so a person's monthly figures sum to a little less than the sum of per-paper counts.
Writes raw/monthly.json: {slug: {"YYYY-MM": n}}.
"""
import argparse
import collections
import sys

from common import RAW, SCHOLAR, TODAY, OpenAlexBudget, load_json, load_roster, save_json
from fetch_openalex import api

OUT = RAW / "monthly.json"


def citing_months(work_ids):
    seen = {}
    for i in range(0, len(work_ids), 40):
        cursor = "*"
        while cursor:
            r = api("works", filter="cites:" + "|".join(work_ids[i:i + 40]), select="id,publication_date", **{"per-page": 200, "cursor": cursor})
            for w in r["results"]:
                if w.get("publication_date"):
                    seen[w["id"]] = w["publication_date"][:7]
            cursor = r["meta"].get("next_cursor") if r["results"] else None
    return collections.Counter(seen.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    snaps = load_json(SCHOLAR, {})
    out = load_json(OUT, {})
    for p in load_roster():
        if a.only and p["slug"] != a.only:
            continue
        s = snaps.get(p["slug"])
        if not s or s.get("source") != "openalex":
            continue
        ids = sorted({x["openalex"] for x in s["papers"] if x.get("openalex") and x.get("cites", 0) > 0})
        if not ids:
            continue
        months = citing_months(ids)
        out[p["slug"]] = {"months": dict(sorted(months.items())), "fetched": TODAY.isoformat(), "citing": sum(months.values())}
        save_json(OUT, out)
        print(f"  {p['slug']}: {sum(months.values())} distinct citing papers over {len(months)} months", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except OpenAlexBudget as e:
        sys.exit(str(e))
