#!/usr/bin/env python3
"""Download the ranking tables into raw/: CORE conference ranks and SCImago journal quartiles.

    python3 fetch_rankings.py [--core ICORE2026] [--sjr 2024]

CORE: portal.core.edu.au CSV export (all pages in one file per edition).
SCImago: journalrank.php CSV; `SJR Best Quartile` is Q1 when the journal is Q1 in any of its categories.
Both are cached; delete the file to refresh.
"""
import argparse
import subprocess
import sys

from common import RAW

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
    ap.add_argument("--core", default="ICORE2026")
    ap.add_argument("--sjr", default="2024")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    core = RAW / f"core_{a.core}.csv"
    if not core.exists():
        curl(f"https://portal.core.edu.au/conf-ranks/?search=&by=all&source={a.core}&sort=atitle&page=1&do=Export", core)
    sjr = RAW / f"sjr_{a.sjr}.csv"
    if not sjr.exists():
        curl(f"https://www.scimagojr.com/journalrank.php?year={a.sjr}&out=xls", sjr, "https://www.scimagojr.com/journalrank.php")
    for f in (core, sjr):
        print(f"{f.name}: {sum(1 for _ in f.open(encoding='utf-8', errors='ignore'))} lines")


if __name__ == "__main__":
    main()
