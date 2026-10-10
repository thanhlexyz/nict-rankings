#!/usr/bin/env python3
"""Snapshot of each Scholar profile: totals, citations per year and the full paper list.

    python3 fetch_scholar.py                 # every roster row with a scholar_id
    python3 fetch_scholar.py --only <slug>   # one person
    python3 fetch_scholar.py --details       # also read the paper page where the profile prints a cut author list

Writes scholar.json (replaced per person) and appends one row per person to history.csv, which is where the
monthly graph gets its own points. Google Scholar refuses searches from scripts; profile pages by ID work, so
the IDs are hand-kept in roster.csv. This is a manual snapshot: `make data` never runs it.
"""
import argparse
import csv
import html
import os
import re
import subprocess
import sys
import time

from common import HISTORY, SCHOLAR, TODAY, clear_status, note_status, h_index, i10_index, authors_include, load_json, load_roster, save_json, split_authors

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
PAGE = 100
DELAY = 8.0
DETAIL_DELAY = 6.0


def get(url, tries=2):
    """curl, not python-requests: Google answers a Python client with 429 where curl is served.

    With SCHOLAR_VIA_SSH=<host> the same curl runs on that host (an ssh alias), which has its own address.
    """
    cmd = ["curl", "-sL", "--max-time", "40", "-A", UA, "-w", "\n%{http_code} %{url_effective}", url]
    via = os.environ.get("SCHOLAR_VIA_SSH", "").strip()
    if via:
        import shlex
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", via, " ".join(shlex.quote(c) for c in cmd)]
    for i in range(tries):
        out = subprocess.run(cmd, capture_output=True).stdout.decode("utf-8", "ignore")
        body, _, tail = out.rpartition("\n")
        code, _, final = tail.partition(" ")
        if code == "200" and "accounts.google.com" not in final and "/sorry/" not in final:
            clear_status("scholar_block")
            return body
        time.sleep(60 * (i + 1))
    note_status("scholar_block", f"Google Scholar refused requests (HTTP {code}). Wait some minutes, then run fetch_scholar.py --skip-fetched --details.")
    raise RuntimeError(f"Google Scholar refused {url} (HTTP {code}); wait a few minutes and retry")


def text(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def parse_header(h):
    table = [int(x) for x in re.findall(r'<td class="gsc_rsb_std">(\d+)</td>', h)]
    since = re.search(r'<th class="gsc_rsb_sth">Since (\d{4})</th>', h)
    years = [int(y) for y in re.findall(r'<span class="gsc_g_t"[^>]*>(\d{4})</span>', h)]
    bars = re.findall(r'class="gsc_g_a"[^>]*z-index:(\d+)[^>]*><span class="gsc_g_al">(\d+)</span>', h)
    by_year = {}
    if bars and years:
        for z, c in bars:  # a year without citations has no bar; z-index counts back from the last year
            by_year[years[-1] - int(z) + 1] = int(c)
    t = lambda i: table[i] if len(table) > i else 0
    return {
        "name": text(re.search(r'<div id="gsc_prf_in">(.*?)</div>', h) and re.search(r'<div id="gsc_prf_in">(.*?)</div>', h).group(1)),
        "affiliation": text((re.search(r'<div class="gsc_prf_il">(.*?)</div>', h) or [None, ""])[1]),
        "email": text((re.search(r'id="gsc_prf_ivh"[^>]*>(.*?)</div>', h, re.S) or [None, ""])[1]),
        "citations": t(0), "citations_since": t(1), "h_index": t(2), "h_index_since": t(3),
        "i10_index": t(4), "i10_index_since": t(5),
        "since": int(since.group(1)) if since else None,
        "by_year": {str(y): by_year.get(y, 0) for y in range(min(by_year), max(by_year) + 1)} if by_year else {},
    }


def parse_papers(h):
    papers = []
    for row in re.findall(r'<tr class="gsc_a_tr">(.*?)</tr>', h, re.S):
        a = re.search(r'<a href="([^"]*)"[^>]*class="gsc_a_at"[^>]*>(.*?)</a>', row, re.S)
        if not a:
            continue
        grays = re.findall(r'<div class="gs_gray">(.*?)</div>', row, re.S)
        cites = re.search(r'class="gsc_a_ac[^"]*"[^>]*>(\d*)</a>', row)
        year = re.search(r'class="gsc_a_h[^"]*"[^>]*>(\d{4})</span>', row)
        key = re.search(r"citation_for_view=([^&\"]+)", a.group(1))
        authors = text(grays[0]) if grays else ""
        papers.append({
            "key": html.unescape(key.group(1)) if key else "", "title": text(a.group(2)),
            "authors": authors, "authors_cut": authors.endswith("...") or authors.endswith("…"),
            "venue": text(grays[1]) if len(grays) > 1 else "",
            "year": int(year.group(1)) if year else None,
            "cites": int(cites.group(1)) if cites and cites.group(1) else 0,
        })
    return papers


def read_profile(user):
    papers, start, head = [], 0, None
    while True:
        h = get(f"https://scholar.google.com/citations?hl=en&user={user}&cstart={start}&pagesize={PAGE}&sortby=pubdate")
        if "gsc_prf_in" not in h:
            return None
        if head is None:
            head = parse_header(h)
        page = parse_papers(h)
        papers += page
        if len(page) < PAGE or 'id="gsc_bpf_more"' in h and "disabled" in re.search(r'<button[^>]*id="gsc_bpf_more"[^>]*>', h).group(0):
            break
        start += PAGE
        time.sleep(DELAY)
    return {**head, "papers": papers}


def read_details(user, paper):
    """The paper page prints the whole author list."""
    h = get(f"https://scholar.google.com/citations?view_op=view_citation&hl=en&user={user}&citation_for_view={paper['key']}")
    fields = {text(k): text(v) for k, v in re.findall(r'<div class="gsc_oci_field">(.*?)</div><div class="gsc_oci_value"[^>]*>(.*?)</div>', h, re.S)}
    return fields.get("Authors", "")


def append_history(p, prof, n):
    fresh = not HISTORY.exists()
    with HISTORY.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if fresh:
            w.writerow(["date", "slug", "citations", "h_index", "i10_index", "citations_since", "h_index_since", "i10_index_since", "papers"])
        w.writerow([TODAY.isoformat(), p["slug"], prof["citations"], prof["h_index"], prof["i10_index"],
                    prof["citations_since"], prof["h_index_since"], prof["i10_index_since"], n])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--details", action="store_true")
    ap.add_argument("--skip-fetched", action="store_true", help="leave profiles already in scholar.json alone")
    args = ap.parse_args()
    for p in load_roster():
        if args.only and p["slug"] != args.only:
            continue
        if not p["scholar_id"] or (args.skip_fetched and p["slug"] in load_json(SCHOLAR, {})):
            continue
        try:
            prof = read_profile(p["scholar_id"])
        except RuntimeError as e:
            print(f"  {p['slug']}: {e}", file=sys.stderr)
            continue
        if not prof:
            print(f"  {p['slug']}: profile {p['scholar_id']} could not be read", file=sys.stderr)
            continue
        if args.details:
            cut = [x for x in prof["papers"] if x["authors_cut"] and not authors_include(split_authors(x["authors"]), p["names"])]
            for x in cut:
                try:
                    full = read_details(p["scholar_id"], x)
                except RuntimeError as e:  # blocked: keep what we have; those papers stay "unconfirmed"
                    print(f"  {p['slug']}: details stopped ({e})", file=sys.stderr)
                    break
                if full:
                    x["authors"], x["authors_cut"] = full, False
                time.sleep(DETAIL_DELAY)
        data = load_json(SCHOLAR, {})  # other scripts may have written meanwhile
        data[p["slug"]] = {**prof, "user": p["scholar_id"], "url": f"https://scholar.google.com/citations?user={p['scholar_id']}",
                           "fetched": TODAY.isoformat()}
        save_json(SCHOLAR, data)
        counts = [x["cites"] for x in prof["papers"]]
        append_history(p, prof, len(counts))
        print(f"  {p['slug']}: {prof['name']} | cited by {prof['citations']}, h {prof['h_index']} "
              f"(papers sum {sum(counts)}, h {h_index(counts)}), {len(counts)} papers", file=sys.stderr)
        time.sleep(DELAY)
    print(f"{len(load_json(SCHOLAR, {}))} profiles -> {SCHOLAR}")


if __name__ == "__main__":
    main()
