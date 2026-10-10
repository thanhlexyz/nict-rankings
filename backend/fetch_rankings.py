#!/usr/bin/env python3
"""Download the ranking tables into raw/: CORE conference ranks and SCImago journal quartiles.

    python3 fetch_rankings.py [--core ICORE2026 CORE2023 ...] [--sjr 2024]

CORE: portal.core.edu.au CSV export (all pages in one file per edition).
SCImago: journalrank.php CSV; `SJR Best Quartile` is Q1 when the journal is Q1 in any of its categories.
Both are cached; delete the file to refresh.
"""
import argparse
import subprocess
import sys

from common import RAW

# A conference keeps its rank from the newest edition that lists it: CORE dropped some (IEEE ICC, rank B in 2018)
# from later lists, so older editions are a fallback, never an override.
EDITIONS = ["ICORE2026", "CORE2023", "CORE2021", "CORE2020", "CORE2018", "CORE2017", "CORE2014"]
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def curl(url, out, referer=None):
    cmd = ["curl", "-sL", "--max-time", "180", "-A", UA, "-o", str(out), "-w", "%{http_code}"]
    if referer:
        cmd += ["-e", referer]
    code = subprocess.run(cmd + [url], capture_output=True).stdout.decode()
    if code != "200":
        out.unlink(missing_ok=True)
        sys.exit(f"{url}: HTTP {code}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", nargs="+", default=EDITIONS, help="CORE editions, newest first")
    ap.add_argument("--sjr", default="2024")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    cores = []
    for ed in a.core:
        core = RAW / f"core_{ed}.csv"
        if not core.exists():
            curl(f"https://portal.core.edu.au/conf-ranks/?search=&by=all&source={ed}&sort=atitle&page=1&do=Export", core)
        cores.append(core)
    sjr = RAW / f"sjr_{a.sjr}.csv"
    if not sjr.exists():
        curl(f"https://www.scimagojr.com/journalrank.php?year={a.sjr}&out=xls", sjr, "https://www.scimagojr.com/journalrank.php")
    for f in (*cores, sjr):
        print(f"{f.name}: {sum(1 for _ in f.open(encoding='utf-8', errors='ignore'))} lines")


if __name__ == "__main__":
    main()
