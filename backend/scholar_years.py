#!/usr/bin/env python3
"""Per-year Scholar citations of the *validated* articles: the Yearly page's source.

    SCHOLAR_VIA_SSH=<host> python3 scholar_years.py [--slug <slug>] [--redo]

Scholar shows a per-year citation bar chart for a whole profile and for each article. With the cleaning of profile_check.py
(articles that name the person, in their field):
  cleaned per year = profile per year - (per-year of the articles set aside)     when fewer articles are set aside than kept
                   = sum of per-year of the kept articles                          otherwise
so the fewer paper pages are read. When nothing is set aside the profile's own bars are the answer.
Paper histograms are cached in raw/scholar_paper_years.json; results go to profile_checks.json (cleaned_by_year, years_method).
"""
import argparse
import re
import sys
import time

from common import BACKEND, RAW, TODAY, rebuild_site, fold, load_json, load_roster, save_json
from fetch_scholar import DELAY, DETAIL_DELAY, get, read_profile

OUT = BACKEND / "profile_checks.json"
CACHE = RAW / "scholar_paper_years.json"


def paper_years(user, key):
    h = get(f"https://scholar.google.com/citations?view_op=view_citation&hl=en&user={user}&citation_for_view={key}")
    return {y: int(n) for y, n in re.findall(r'as_ylo=(\d{4})[^"]*"[^>]*class="gsc_oci_g_a"[^>]*><span class="gsc_oci_g_al">(\d+)</span>', h)}


PAGE_DELAY = 12.0   # paper pages are throttled hard (about 14 reads in two minutes triggers a block)
WAIT = 1200         # after a block, wait 20 minutes and resume: the cache keeps what was read
TRIES = 8


def pages_needed(c):
    kept = sum(1 for r in c["rows"] if r["status"] == "named" and r["cites"] > 0)
    out = sum(1 for r in c["rows"] if r["status"] != "named" and r["cites"] > 0)
    return 0 if not out else min(kept, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--max-pages", type=int, default=10**9, help="only people needing at most this many paper pages")
    ap.add_argument("--min-pages", type=int, default=0)
    ap.add_argument("--reverse", action="store_true", help="work the list from the other end (a second worker meets the first in the middle)")
    a = ap.parse_args()
    # statuses first re-judged with the current name matcher (no Scholar request), so kept/set-aside is current
    import subprocess
    subprocess.run([sys.executable, str(BACKEND / "profile_check.py"), "--rescore"], capture_output=True)
    people = {r["slug"]: r for r in load_roster()}
    allc = load_json(OUT, {})
    order = [a.slug] if a.slug else sorted(allc, key=lambda s: pages_needed(allc[s]), reverse=a.reverse)
    for slug in order:
        checks = load_json(OUT, {})
        c, p = checks.get(slug), people.get(slug)
        if not c or not p or not p["scholar_id"] or (c.get("cleaned_by_year") is not None and not a.redo):
            continue
        if not (a.min_pages <= pages_needed(c) <= a.max_pages):
            continue
        for attempt in range(TRIES):
          try:
            prof = read_profile(p["scholar_id"])
            time.sleep(DELAY)
            claimed = prof["by_year"]
            by_title = {fold(x["title"]): x["key"] for x in prof["papers"]}
            kept = [r for r in c["rows"] if r["status"] == "named" and r["cites"] > 0]
            out = [r for r in c["rows"] if r["status"] != "named" and r["cites"] > 0]
            cache = load_json(CACHE, {})

            def years_of(rows):
                tot = {}
                for r in rows:
                    k = by_title.get(fold(r["title"]))
                    if not k:
                        continue
                    ck = f"{p['scholar_id']}:{k}"
                    if ck not in cache:
                        cache[ck] = paper_years(p["scholar_id"], k)
                        save_json(CACHE, load_json(CACHE, {}) | {ck: cache[ck]})   # keep what was read, merge with other runs
                        time.sleep(PAGE_DELAY)
                    for y, n in cache[ck].items():
                        tot[y] = tot.get(y, 0) + n
                return tot

            if not out:
                cleaned, method = dict(claimed), "profile (no article set aside)"
            elif len(out) <= len(kept):
                sub = years_of(out)
                cleaned = {y: max(claimed.get(y, 0) - sub.get(y, 0), 0) for y in set(claimed) | set(sub)}
                method = f"profile minus {len(out)} set-aside articles"
            else:
                cleaned, method = years_of(kept), f"sum of {len(kept)} kept articles"
            break
          except RuntimeError as e:
            print(f"  {slug}: blocked ({e.__class__.__name__}); waiting {WAIT // 60} min, attempt {attempt + 1}/{TRIES}", file=sys.stderr)
            time.sleep(WAIT)
        else:
            print(f"  {slug}: gave up after {TRIES} attempts", file=sys.stderr)
            continue
        checks = load_json(OUT, {})
        checks[slug].update({"claimed_by_year": {y: claimed[y] for y in sorted(claimed)}, "cleaned_by_year": {y: cleaned[y] for y in sorted(cleaned)},
                             "years_method": method, "years_fetched": TODAY.isoformat()})
        save_json(OUT, checks)
        rebuild_site()
        print(f"  {slug}: {method}; cleaned total {sum(cleaned.values())} of profile {sum(claimed.values())} (per-year bars)", file=sys.stderr)


if __name__ == "__main__":
    main()
