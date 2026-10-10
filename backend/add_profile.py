#!/usr/bin/env python3
"""Add a Scholar profile that is not in the workbook to roster.csv.

    python3 add_profile.py <scholar URL or user id> [<name override>]

Reads the profile's name from the page, appends a row numbered x1, x2, ... and prints it. The row is
`approved=yes`; set `approved` to `no` (with the reason in `notes`) to leave a person off the site.
"""
import csv
import re
import sys
import time

from common import ROSTER, WORK, fold
from fetch_scholar import get, parse_header


def main():
    if sys.argv[1] == "--pending":  # work/pending_ids.txt: one ID or URL per line, emptied as rows are added
        todo = [l.strip() for l in (WORK / "pending_ids.txt").read_text().splitlines() if l.strip()]
        left, done = [], []
        for u in dict.fromkeys(todo):
            try:
                uid, _, extra = u.partition("|")
                add(uid.strip(), None, extra)
            except RuntimeError as e:  # blocked: keep this and every later ID for the next run
                print(f"  stopped at {u}: {e}", file=sys.stderr)
                left += [x for x in dict.fromkeys(todo) if x not in done]
                break
            done.append(u)
            time.sleep(10)
        (WORK / "pending_ids.txt").write_text("".join(l + "\n" for l in left))
        return
    add(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)


def add_researchmap(rm, override):
    from fetch_researchmap import curl_json, pick
    rows = list(csv.DictReader(ROSTER.open(encoding="utf-8")))
    fields = list(rows[0].keys())
    if any(r.get("researchmap_id") == rm for r in rows):
        print(f"{rm} is already on the roster")
        return
    prof = curl_json(f"https://api.researchmap.jp/{rm}")
    family, given = pick(prof.get("family_name")), pick(prof.get("given_name"))
    ja_f, ja_g = (prof.get("family_name") or {}).get("ja", ""), (prof.get("given_name") or {}).get("ja", "")
    name = override or f"{given.title()} {family.title()}".strip()
    n = 1 + max([int(r["row"][1:]) for r in rows if re.fullmatch(r"x\d+", r["row"])] or [0])
    row = {k: "" for k in fields}
    row.update(row=f"x{n}", slug=re.sub(r"\s+", "-", fold(name)), name=name, name_ja=f"{ja_f} {ja_g}".strip(),
               aliases=f"{family.title()} {given.title()}", researchmap_id=rm, approved="yes",
               notes=f"Added by the maintainer; not in the screening workbook. No Google Scholar profile; papers from Researchmap (https://researchmap.jp/{rm}), citations from OpenAlex.")
    with ROSTER.open("a", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fields).writerow(row)
    print(row)


def add(arg, override, extra=""):
    m = re.search(r"researchmap\.jp/([A-Za-z0-9_\-]+)", arg)
    if m:
        return add_researchmap(m.group(1), override)
    note, _, rest = extra.partition("|")
    p_from, _, p_to = rest.partition("|")
    user = re.search(r"user=([A-Za-z0-9_-]{12})", arg)
    user = user.group(1) if user else arg
    rows = list(csv.DictReader(ROSTER.open(encoding="utf-8")))
    fields = list(rows[0].keys())
    for c in ("period_from", "period_to"):
        if c not in fields:
            fields.append(c)
    if any(r["scholar_id"] == user for r in rows):
        print(f"{user} is already on the roster")
        return
    head = parse_header(get(f"https://scholar.google.com/citations?hl=en&user={user}"))
    name = override or head["name"]
    # a workbook person who still lacks an ID: fill that row instead of adding a duplicate
    want = frozenset(fold(name).split())
    for r in rows:
        forms = [r["name"], r["name_ja"], *r["aliases"].split(";")]
        if not r["scholar_id"] and any(frozenset(fold(x).split()) == want for x in forms if x):
            r["scholar_id"] = user
            r["notes"] = (r["notes"] + f" Scholar: {head['affiliation']} ({head['email']}). {note}").strip()
            r["period_from"], r["period_to"] = p_from or r.get("period_from", ""), p_to or r.get("period_to", "")
            with ROSTER.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fields)
                w.writeheader()
                w.writerows(rows)
            print(f"{name}: filled row {r['row']}")
            return
    n = 1 + max([int(r["row"][1:]) for r in rows if re.fullmatch(r"x\d+", r["row"])] or [0])
    row = {k: "" for k in fields}
    row.update(row=f"x{n}", slug=re.sub(r"\s+", "-", fold(name)) or f"x{n}", name=name, scholar_id=user, approved="yes",
               notes=f"Added by the maintainer; not in the screening workbook. Scholar: {head['affiliation']} ({head['email']}). {note}".strip(),
               period_from=p_from, period_to=p_to)
    with ROSTER.open("a", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fields).writerow(row)
    print(row)


if __name__ == "__main__":
    main()
