#!/usr/bin/env python3
"""Build frontend/data/*.json and the page stubs from the Scholar snapshot, OpenAlex records and rankings.

    python3 build_site_data.py

Reads scholar.json, raw/openalex.json (optional), history.csv, xlsx_history.csv, roster.csv, venue_overrides.csv,
paper_overrides.csv. Writes work/build_report.txt with what needs a human (unclassified venues, unconfirmed papers).
"""
import collections
import csv
import json
import shutil
from pathlib import Path

import charts
from common import (STATUS, FRONTEND, FROM_YEAR, HISTORY, OPENALEX, PAPER_OVERRIDES, SCHOLAR, TODAY, WORK, XLSX_HISTORY,
                    h_index, i10_index, load_json, load_roster, read_csv, save_json, venue_core)
from validate import COUNTED, paper_status, records_for
from venues import classify

DATA = FRONTEND / "data"
CONTENT = FRONTEND / "content" / "people"
STATUS_TEXT = {"verified": "verified by OpenAlex", "listed": "named in Scholar's author list", "maintainer": "confirmed by the maintainer",
               "unconfirmed": "unconfirmed", "outside": "outside the period at NICT", "not_listed": "author list does not name the person"}
VENUE_KEYS = ["journal_q1", "journal_q2", "journal_q3", "journal_q4", "journal_other",
              "conf_astar", "conf_a", "conf_b", "conf_c", "conf_unranked", "preprint", "patent", "other"]


def venue_key(c):
    k = c["kind"]
    if k == "journal":
        return {"Q1": "journal_q1", "Q2": "journal_q2", "Q3": "journal_q3", "Q4": "journal_q4"}.get(c["quartile"], "journal_other")
    if k == "conference":
        return {"A*": "conf_astar", "A": "conf_a", "B": "conf_b", "C": "conf_c"}.get(c["core_rank"], "conf_unranked")
    return k if k in ("preprint", "patent") else "other"


def month_of(date):
    return date[:7]


def monthly(slug, row, xlsx, history):
    """month -> citations: the workbook's monthly sheet, then this project's own snapshots (a later source wins)."""
    out = {}
    if row:
        for r in xlsx:
            if r["row"] == row and r["sheet"] == "Total citation":
                out[r["month"]] = int(float(r["value"]))
    for r in history:
        if r["slug"] == slug:
            out[month_of(r["date"])] = int(r["citations"])
    return dict(sorted(out.items()))


def build_person(p, snap, cache, overrides, xlsx, history, report):
    papers = snap["papers"]
    rows, vcount, vcount_since = [], collections.Counter(), collections.Counter()
    tot = collections.Counter()
    by_year_counted = collections.Counter()
    for x in papers:
        recs = records_for(x, p, cache)
        issn = [i for r in recs for i in r.get("issn", [])]
        status, reason = paper_status(x, p, recs, overrides.get((p["slug"], x["key"])), snap.get("source", "scholar"))
        issn += x.get("issn", [])
        is_conf = (recs and recs[0].get("source_type") == "conference") or x.get("rm_type", "").endswith("conference_proceedings")
        c = classify(x["venue"] or (recs[0].get("source") if recs else "") or "", issns=tuple(issn),
                     oa_type=("conference" if is_conf else None))
        vk = venue_key(c)
        counted = status in COUNTED
        tot[status] += x["cites"]
        tot[status + "_n"] += 1
        if counted:
            vcount[vk] += 1
            by_year_counted[x["year"] or 0] += x["cites"]
            if (x["year"] or 0) >= FROM_YEAR:
                vcount_since[vk] += 1
        if c["kind"] == "unknown" and counted:
            report.append(f"{p['slug']}: venue not classified: {x['venue']!r} ({x['title'][:60]})")
        rows.append({
            "key": x["key"], "title": x["title"], "year": x["year"], "cites": x["cites"], "venue": x["venue"],
            "authors": x["authors"], "kind": c["kind"], "quartile": c["quartile"], "core_rank": c["core_rank"],
            "venue_matched": c["matched"], "venue_how": c["how"], "venue_key": vk,
            "status": status, "status_text": STATUS_TEXT[status], "reason": reason, "counted": counted,
            "oa": [r["id"] for r in recs][:2],
            "url": f"https://scholar.google.com/citations?view_op=view_citation&user={snap['user']}&citation_for_view={x['key']}",
        })
    counted_rows = [r for r in rows if r["counted"]]
    since_rows = [r for r in counted_rows if (r["year"] or 0) >= FROM_YEAR]
    has_claim = snap.get("source", "scholar") == "scholar"
    claimed = snap["citations"]
    counted_c = sum(r["cites"] for r in counted_rows)
    cites = [r["cites"] for r in counted_rows]
    mon = monthly(p["slug"], p["row"] if not p["row"].startswith("x") else "", xlsx, history)
    person = {
        "slug": p["slug"], "name": p["name"], "name_ja": p.get("name_ja", "") if not p.get("name_ja", "").isascii() else "", "scholar_url": snap["url"],
        "affiliation": snap.get("affiliation", ""), "fetched": snap["fetched"], "notes": p.get("notes", ""),
        "source": snap.get("source", "scholar"), "has_claim": has_claim,
        "claimed": {"citations": claimed if has_claim else 0, "h": snap["h_index"] if has_claim else 0,
                    "i10": snap["i10_index"] if has_claim else 0, "since": snap["citations_since"],
                    "h_since": snap["h_index_since"], "i10_since": snap["i10_index_since"],
                    "papers": len(papers), "papers_sum": sum(x["cites"] for x in papers)},
        "counted": {"citations": counted_c, "h": h_index(cites), "i10": i10_index(cites), "papers": len(counted_rows)},
        "unconfirmed": {"citations": tot["unconfirmed"], "papers": tot["unconfirmed_n"]},
        "removed": {"citations": tot["not_listed"], "papers": tot["not_listed_n"]},
        "verified_n": tot["verified_n"] + tot["maintainer_n"],
        "listed_n": tot["listed_n"],
        "ratio": round(counted_c / claimed, 3) if has_claim and claimed else None,
        "removed_share": round(tot["not_listed"] / claimed, 3) if has_claim and claimed else None,
        "since_window": {"papers": len(since_rows), "citations": sum(r["cites"] for r in since_rows),
                         "claimed_since": snap["citations_since"],
                         "h": h_index([r["cites"] for r in since_rows]), "i10": i10_index([r["cites"] for r in since_rows])},
        "venues": {k: vcount.get(k, 0) for k in VENUE_KEYS},
        "venues_since": {k: vcount_since.get(k, 0) for k in VENUE_KEYS},
        "by_year_claimed": snap["by_year"],
        "papers_by_year": dict(sorted(by_year_counted.items())),
        "monthly": mon,
    }
    return person, rows


def collect_issues(roster, snaps, people, report_by_slug):
    """What still needs the maintainer or an external limit to clear. Every item names who is affected and what to do."""
    status = load_json(STATUS, {})
    pending = [l for l in (WORK / "pending_ids.txt").read_text(encoding="utf-8").split("\n") if l.strip()] \
        if (WORK / "pending_ids.txt").exists() else []
    by_slug = {p["slug"]: p for p in people}
    out = []

    def item(group, title, detail, who=(), action="", severity="todo"):
        out.append({"group": group, "title": title, "detail": detail, "action": action, "severity": severity,
                    "who": [{"slug": s, "name": n, "linked": s in by_slug} for s, n in who]})

    if "scholar_block" in status:
        s = status["scholar_block"]
        item("blocked", "Google Scholar is rate-limiting this network", f"{s['message']} (first seen {s['since']}).",
             action="Wait 15 to 30 minutes, then run: make snapshot", severity="blocked")
    if "openalex_budget" in status:
        s = status["openalex_budget"]
        item("blocked", "OpenAlex budget used up", f"{s['message']} (first seen {s['since']}). Affected: citation counts for people without "
             "a Scholar profile, author lists from ORCID, and the independent check of every paper.",
             action="Create a key at openalex.org (free tier first), then in the shell that runs the pipeline: "
                    "export OPENALEX_API_KEY=...  and  make snapshot. Do not paste the key into chat or commit it.", severity="blocked")
    if pending:
        item("blocked", f"{len(pending)} Scholar profile IDs are queued, not yet read",
             "They are in backend/work/pending_ids.txt and join the roster when Google answers.",
             action="Runs automatically in make snapshot (add_profile.py --pending).", severity="blocked")

    no_snap = [r for r in roster if r["slug"] not in snaps]
    no_id = [r for r in no_snap if not (r["scholar_id"] or r.get("researchmap_id") or r.get("orcid"))]
    if no_id:
        item("decide", f"{len(no_id)} people on the screening list have no profile link",
             "Without a Google Scholar, Researchmap or ORCID link their papers can only come from OpenAlex (papers printed with an NICT affiliation).",
             who=[(r["slug"], r["name"]) for r in no_id],
             action="Send a Scholar link (or Researchmap / ORCID) for each, or run fetch_openalex_people.py once OpenAlex has budget.")
    unread = [r for r in roster if r["scholar_id"] and r["slug"] not in snaps]
    if unread:
        item("blocked", f"{len(unread)} Scholar profiles are in the roster but not yet read",
             "The ID is known; Google blocked the page or the run has not reached it. Their rows are missing from the ranking until then.",
             who=[(r["slug"], r["name"]) for r in unread], action="make snapshot", severity="blocked")
    # snapshots with no papers
    for slug, s in snaps.items():
        if not s.get("papers"):
            item("decide", f"{s.get('name', slug)}: the source lists no papers", "The source's profile lists no papers, so the snapshot is empty.",
                 who=[(slug, s.get("name", slug))], action="Decided: take his NICT-affiliated papers from OpenAlex. Runs in make snapshot (fetch_openalex_people.py) once OpenAlex has budget.")
    ex = [r for r in roster if "ex-nict" in (r.get("notes") or "").lower() and not (r.get("period_from") or r.get("period_to"))]
    if ex:
        item("decide", "Years at NICT are not set for people who left",
             "Their whole profile is counted until a period is set in roster.csv (period_from, period_to); papers outside it are listed, not counted.",
             who=[(r["slug"], r["name"]) for r in ex], action="Tell me the years, or fill the two columns in backend/roster.csv.")
    open_name = [r for r in roster if r["slug"] in snaps and snaps[r["slug"]].get("source", "scholar") == "scholar" and not r["openalex_ids"]]
    if open_name:
        item("check", "No confirmed OpenAlex author ID",
             "Their papers are checked by exact title only (and by Scholar's own author list). An author ID makes the independent check stronger.",
             who=[(r["slug"], r["name"]) for r in open_name],
             action="fetch_openalex.py --resolve proposes IDs in work/openalex_candidates.csv; confirm each by hand into roster.csv openalex_ids.")
    uncon = [(p["slug"], f"{p['name']} ({p['unconfirmed']['papers']})") for p in people if p["unconfirmed"]["papers"]]
    if uncon:
        item("check", "Papers whose author list could not be checked",
             "Scholar prints a cut author list that does not show the person and no independent record was found. They are shown, not counted.",
             who=uncon, action="fetch_scholar.py --details --only <slug> reads the full list; or decide per paper in paper_overrides.csv.")
    unclass = [(s, f"{s} ({n})") for s, n in report_by_slug.items() if n]
    if unclass:
        item("check", "Venues the matcher could not classify",
             "Counted papers whose venue is neither a journal in SCImago nor a conference in CORE, nor a preprint or patent. They sit in 'Other'.",
             who=unclass, action="Add rows to backend/venue_overrides.csv (venue, kind, quartile, core_rank).")
    nonscholar = [p for p in people if p["source"] != "scholar"]
    if nonscholar:
        item("info", "People with no Scholar profile figure",
             "Papers come from Researchmap, ORCID or OpenAlex; citation counts are OpenAlex's, which index fewer papers than Scholar, so their totals are not comparable with Scholar totals.",
             who=[(p["slug"], f"{p['name']} ({p['source']})") for p in nonscholar])
    return out


def main():
    scholar = load_json(SCHOLAR, {})
    cache = load_json(OPENALEX, {"works_by_author": {}, "titles": {}})
    overrides = {(r["slug"], r["key"]): r for r in read_csv(PAPER_OVERRIDES)}
    xlsx, history = read_csv(XLSX_HISTORY), read_csv(HISTORY)
    report, people, paper_files = [], [], {}
    waiting = []
    for p in load_roster():
        snap = scholar.get(p["slug"])
        if not snap:
            waiting.append(f"{p['slug']}: no Scholar snapshot" + ("" if p["scholar_id"] else " (no profile ID in roster.csv)"))
            continue
        person, rows = build_person(p, snap, cache, overrides, xlsx, history, report)
        people.append(person)
        paper_files[p["slug"]] = rows
        if person["unconfirmed"]["papers"]:
            report.append(f"{p['slug']}: {person['unconfirmed']['papers']} unconfirmed papers (cut author lists; run fetch_scholar.py --details --only {p['slug']})")
    people.sort(key=lambda r: (-r["counted"]["citations"], r["name"]))

    # overview
    sum_ = lambda f: sum(f(r) for r in people)
    months = sorted({m for r in people for m in r["monthly"]})
    cohort = [r for r in people if months and months[0] in r["monthly"] and months[-1] in r["monthly"]]
    total_by_month = {m: sum(r["monthly"][m] for r in cohort) for m in months if all(m in r["monthly"] for r in cohort)}
    venues_all = {k: sum_(lambda r: r["venues"][k]) for k in VENUE_KEYS}
    venues_since = {k: sum_(lambda r: r["venues_since"][k]) for k in VENUE_KEYS}
    by_year = collections.Counter()
    for r in people:
        for y, v in r["by_year_claimed"].items():
            by_year[y] += v
    overview = {
        "built": TODAY.isoformat(), "from_year": FROM_YEAR, "people": len(people),
        "claimed": sum_(lambda r: r["claimed"]["citations"]), "claimed_people": sum_(lambda r: 1 if r["has_claim"] else 0),
        "counted": sum_(lambda r: r["counted"]["citations"] if r["has_claim"] else 0),
        "counted_other": sum_(lambda r: 0 if r["has_claim"] else r["counted"]["citations"]),
        "other_people": sum_(lambda r: 0 if r["has_claim"] else 1),
        "unconfirmed": sum_(lambda r: r["unconfirmed"]["citations"]), "removed": sum_(lambda r: r["removed"]["citations"]),
        "papers": sum_(lambda r: r["claimed"]["papers"]), "papers_counted": sum_(lambda r: r["counted"]["papers"]),
        "papers_removed": sum_(lambda r: r["removed"]["papers"]), "papers_unconfirmed": sum_(lambda r: r["unconfirmed"]["papers"]),
        "claimed_since": sum_(lambda r: r["claimed"]["since"]), "counted_since": sum_(lambda r: r["since_window"]["citations"]),
        "papers_since": sum_(lambda r: r["since_window"]["papers"]),
        "venues": venues_all, "venues_since": venues_since, "by_year": dict(sorted(by_year.items())),
        "months": months, "cohort": [r["slug"] for r in cohort], "total_by_month": total_by_month,
        "waiting": waiting,
    }

    # charts (inline SVG)
    seg = [("counted", "s1", "Counted"), ("unconfirmed", "s2", "Unconfirmed"), ("removed", "s3", "Author list does not name the person")]
    rows_c = [(r["name"], f"people/{r['slug']}/", {"counted": r["counted"]["citations"], "unconfirmed": r["unconfirmed"]["citations"],
                                                   "removed": r["removed"]["citations"]}) for r in people]  # bar length = papers on the profile
    jq = [("journal_q1", "t0", "Q1"), ("journal_q2", "t1", "Q2"), ("journal_q3", "t2", "Q3"), ("journal_q4", "t3", "Q4"),
          ("journal_other", "t4", "Journal, not in SCImago")]
    cr = [("conf_astar", "t0", "A*"), ("conf_a", "t1", "A"), ("conf_b", "t2", "B"), ("conf_c", "t3", "C"), ("conf_unranked", "t4", "Unranked")]
    ch = {
        "citations": charts.stacked_h(rows_c, seg),
        "citations_legend": charts.legend([(c, n) for _, c, n in seg]),
        "years": charts.bars_v([(y, v) for y, v in overview["by_year"].items() if int(y) >= 2010], from_x=str(FROM_YEAR)),
        "journals": charts.stacked_h([(r["name"], f"people/{r['slug']}/", r["venues"]) for r in people], jq),
        "journals_legend": charts.legend([(c, n) for _, c, n in jq]),
        "conferences": charts.stacked_h([(r["name"], f"people/{r['slug']}/", r["venues"]) for r in people], cr),
        "conferences_legend": charts.legend([(c, n) for _, c, n in cr]),
        "journals_since": charts.stacked_h([(r["name"], f"people/{r['slug']}/", r["venues_since"]) for r in people], jq),
        "conferences_since": charts.stacked_h([(r["name"], f"people/{r['slug']}/", r["venues_since"]) for r in people], cr),
        "monthly_total": charts.lines([("Total (cohort)", "s1", total_by_month)], list(total_by_month)) if len(total_by_month) > 1 else "",
        "monthly_people": {r["slug"]: charts.lines([(r["name"], "s1", r["monthly"])], list(r["monthly"]), width=560, height=170)
                           for r in people if len(r["monthly"]) > 1},
        "spark": {r["slug"]: charts.spark(list(r["monthly"].values())) for r in people},
        "person_years": {r["slug"]: charts.bars_v([(y, v) for y, v in r["by_year_claimed"].items()], from_x=str(FROM_YEAR))
                         for r in people if r["by_year_claimed"]},
    }

    unclassified = collections.Counter(line.split(":", 1)[0] for line in report if "venue not classified" in line)
    roster_all = load_roster()
    issues = collect_issues(roster_all, scholar, people, unclassified)

    DATA.mkdir(parents=True, exist_ok=True)
    save_json(DATA / "issues.json", issues)
    save_json(DATA / "people.json", people)
    save_json(DATA / "overview.json", overview)
    save_json(DATA / "charts.json", ch)
    pdir = DATA / "papers"
    shutil.rmtree(pdir, ignore_errors=True)
    for slug, rows in paper_files.items():
        save_json(pdir / f"{slug}.json", rows)
    shutil.rmtree(CONTENT, ignore_errors=True)
    CONTENT.mkdir(parents=True, exist_ok=True)
    (CONTENT / "_index.md").write_text('---\ntitle: "People"\nheadless: false\n_build:\n  render: never\n---\n', encoding="utf-8")
    for r in people:
        (CONTENT / f"{r['slug']}.md").write_text(f'---\ntitle: "{r["name"]}"\nslug: "{r["slug"]}"\nname_ja: "{r["name_ja"]}"\n---\n', encoding="utf-8")
    WORK.mkdir(exist_ok=True)
    (WORK / "build_report.txt").write_text("\n".join(waiting + report) + "\n", encoding="utf-8")
    print(f"{len(people)} people, claimed {overview['claimed']:,}, counted {overview['counted']:,}, "
          f"unconfirmed {overview['unconfirmed']:,}, not listed {overview['removed']:,}; {len(waiting)} waiting, {len(report)} notes")


if __name__ == "__main__":
    main()
