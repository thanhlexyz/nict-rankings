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
import cooperation
from common import (BACKEND as BACKEND_DIR, ACTIVE_SOURCES, RAW, STATUS, FRONTEND, FROM_YEAR, HISTORY, OPENALEX, PAPER_OVERRIDES, SCHOLAR, TODAY, WORK, XLSX_HISTORY,
                    h_index, i10_index, load_json, load_roster, read_csv, save_json, venue_core)
from common import SCHOLAR_PREPRINTS, SELF_REPORTED, title_key
from validate import COUNTED, paper_status, records_for
from venues import classify

DATA = FRONTEND / "data"
CONTENT = FRONTEND / "content" / "people"
STATUS_TEXT = {"verified": "verified by OpenAlex", "listed": "named in Scholar's author list", "maintainer": "confirmed by the maintainer",
               "unconfirmed": "unconfirmed", "self_reported": "listed on the person's own page (unofficial)", "outside": "outside the period at NICT", "not_listed": "author list does not name the person"}
VENUE_KEYS = ["journal_q1", "journal_q2", "journal_q3", "journal_q4", "journal_other",
              "conf_astar", "conf_a", "conf_b", "conf_c", "conf_unranked", "preprint", "patent", "other"]


def venue_key(c):
    k = c["kind"]
    if k == "journal":
        return {"Q1": "journal_q1", "Q2": "journal_q2", "Q3": "journal_q3", "Q4": "journal_q4"}.get(c["quartile"], "journal_other")
    if k == "conference":
        return {"A*": "conf_astar", "A": "conf_a", "B": "conf_b", "C": "conf_c"}.get(c["core_rank"], "conf_unranked")
    return k if k in ("preprint", "patent") else "other"


# Order of paper classes, best first: Conf A* > Q1 > Conf A > Q2 > Conf B > the rest (Q3, Q4, C, unranked, other).
CLASS_RANK = {"conf_astar": 6, "journal_q1": 5, "conf_a": 4, "journal_q2": 3, "conf_b": 2}
CLASS_COLOR = {"conf_astar": "h0", "conf_a": "h1", "conf_b": "h2", "conf_c": "h3", "conf_unranked": "n",
               "journal_q1": "c0", "journal_q2": "c1", "journal_q3": "c2", "journal_q4": "c3", "journal_other": "n",
               "preprint": "n", "patent": "n", "other": "n"}  # conferences warm, journals cool, no rank grey
CLASS_LABEL = {"conf_astar": "Conf. A*", "journal_q1": "Journal Q1", "conf_a": "Conf. A", "journal_q2": "Journal Q2", "conf_b": "Conf. B",
               "journal_q3": "Journal Q3", "journal_q4": "Journal Q4", "journal_other": "Journal, not in SCImago",
               "conf_c": "Conf. C", "conf_unranked": "Conf. unranked", "preprint": "Preprint", "patent": "Patent", "other": "Other"}


def month_of(date):
    return date[:7]


def monthly(slug, row, xlsx, history):
    """-> (own snapshots, workbook): month -> citations. The workbook series is Scholar's, a different measure, so it is
    kept apart and drawn as its own line."""
    own = {month_of(r["date"]): int(r["citations"]) for r in history if r["slug"] == slug}
    wb = {}
    if row:
        for r in xlsx:
            if r["row"] == row and r["sheet"] == "Total citation":
                wb[r["month"]] = int(float(r["value"]))
    return dict(sorted(own.items())), dict(sorted(wb.items()))


def fold_title(t):
    from common import fold
    return fold(t)


def jaccard(a, b):
    a, b = set(a.split()), set(b.split())
    return len(a & b) / len(a | b) if a | b else 0


def apply_self_reported(slug, papers, mine):
    """Rows from self_reported.csv: a paper already in the list is confirmed by the person's own page (and takes the
    page's venue when the list shows only a preprint); a paper missing from the list is added, counted, and tagged."""
    papers = [dict(x) for x in papers]
    for s in mine:
        k = title_key(s["title"])
        hit = next((x for x in papers if title_key(x["title"]) == k or
                    jaccard(fold_title(x["title"]), fold_title(s["title"])) >= 0.8), None)
        own = "Scholar profile" if "scholar.google" in s["source_url"] else "page"
        note = f"Listed as {s['state']} on the person's own {own} ({s['source_url']}): unofficial confirmation."
        if s["state"] == "preprint":
            note = f"Preprint on the person's Scholar profile ({s['source_url']}), not in OpenAlex; citations are Scholar's: unofficial."
        if hit:
            hit["self_note"], hit["self_venue"] = note, s["venue"]
        else:
            papers.append({"key": "self:" + k[:24], "title": s["title"], "authors": s["authors"], "authors_cut": False,
                           "venue": s["venue"], "year": int(s["year"]) if s["year"] else None,
                           "cites": int(s.get("cites") or 0),
                           "self_reported": True, "self_note": note, "self_venue": s["venue"]})
    return papers


def build_person(p, snap, cache, overrides, xlsx, history, report, self_rows=()):
    papers = apply_self_reported(p["slug"], snap["papers"], [r for r in self_rows if r["slug"] == p["slug"]])
    rows, vcount, vcount_since = [], collections.Counter(), collections.Counter()
    tot = collections.Counter()
    by_year_counted = collections.Counter()
    got_by_year = collections.Counter()  # citations received per year by the counted papers (OpenAlex counts_by_year)
    excluded = 0
    for x in papers:
        ov = overrides.get((p["slug"], x["key"]))
        if ov and ov["decision"] == "no":  # the maintainer says it is not this person's paper: not listed at all
            excluded += 1
            continue
        recs = records_for(x, p, cache)
        issn = [i for r in recs for i in r.get("issn", [])]
        status, reason = paper_status(x, p, recs, overrides.get((p["slug"], x["key"])), snap.get("source", "scholar"))
        if x.get("self_note") and status not in ("not_listed", "outside") or x.get("self_reported"):
            if status in ("unconfirmed",) or x.get("self_reported"):
                status, reason = "self_reported", x["self_note"]
            else:
                reason += " " + x["self_note"]
        issn += x.get("issn", [])
        is_conf = (recs and recs[0].get("source_type") == "conference") or x.get("rm_type", "").endswith("conference_proceedings")
        c = classify(x["venue"] or (recs[0].get("source") if recs else "") or "", issns=tuple(issn),
                     oa_type=("conference" if is_conf else None), year=x.get("year"))
        if x.get("self_venue"):  # the person's own page names the venue cleanly; the profile line may be an arXiv note
            c2 = classify(x["self_venue"], year=x.get("year"))
            if c2["kind"] in ("conference", "journal") and (c2["how"] in ("CORE", "SJR") or c["kind"] in ("preprint", "unknown", "other")
                                                            or c["how"] in ("not in SJR", "not in CORE")):
                c = {**c2, "how": c2["how"] + " (venue from the person's own page)"}
        vk = venue_key(c)
        counted = status in COUNTED
        tot[status] += x["cites"]
        tot[status + "_n"] += 1
        if counted:
            for y, n in (x.get("by_year") or {}).items():
                got_by_year[y] += n
            vcount[vk] += 1
            by_year_counted[x["year"] or 0] += x["cites"]
            if (x["year"] or 0) >= FROM_YEAR:
                vcount_since[vk] += 1
        if c["kind"] == "unknown" and counted:
            report.append(f"{p['slug']}: venue not classified: {x['venue']!r} ({x['title'][:60]})")
        rows.append({
            "key": x["key"], "title": x["title"], "year": x["year"], "cites": x["cites"], "venue": x["venue"],
            "authors": x["authors"], "kind": c["kind"], "quartile": c["quartile"], "core_rank": c["core_rank"],
            "venue_matched": c["matched"], "venue_how": c["how"], "venue_edition": c.get("edition", ""), "venue_key": vk,
            "class_rank": CLASS_RANK.get(vk, 1), "class_label": CLASS_LABEL[vk], "class_color": CLASS_COLOR[vk],
            "status": status, "status_text": STATUS_TEXT[status], "reason": reason, "counted": counted,
            "unofficial": bool(x.get("self_note")),
            "oa": [r["id"] for r in recs][:2],
            "url": f"https://scholar.google.com/citations?view_op=view_citation&user={snap['user']}&citation_for_view={x['key']}",
        })
    rows.sort(key=lambda r: (not r["counted"], -r["class_rank"], -r["cites"], -(r["year"] or 0)))  # counted first, then by class
    counted_rows = [r for r in rows if r["counted"]]
    since_rows = [r for r in counted_rows if (r["year"] or 0) >= FROM_YEAR]
    has_claim = snap.get("source", "scholar") == "scholar"
    claimed = snap["citations"]
    counted_c = sum(r["cites"] for r in counted_rows)
    cites = [r["cites"] for r in counted_rows]
    mon, mon_wb = monthly(p["slug"], p["row"] if not p["row"].startswith("x") else "", xlsx, history)

    person = {
        "slug": p["slug"], "name": p["name"], "name_ja": p.get("name_ja", "") if not p.get("name_ja", "").isascii() else "", "scholar_url": snap["url"],
        "affiliation": snap.get("affiliation", ""), "fetched": snap["fetched"], "notes": p.get("notes", ""),
        "source": snap.get("source", "scholar"), "has_claim": has_claim, "excluded_n": excluded,
        "incomplete": not snap.get("ids_confirmed"), "incomplete_reason": (
            "OpenAlex author IDs are provisional (not confirmed by an ORCID, a profile cross-check or the maintainer): the list may include a "
            "namesake's papers or miss some." if not snap.get("ids_confirmed") else ""),
        "author_ids": snap.get("author_ids", []),
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
        "by_year": dict(sorted(got_by_year.items())),
        "received_since": sum(c for y, c in got_by_year.items() if int(y) >= FROM_YEAR),
        "papers_by_year": dict(sorted(by_year_counted.items())),
        "monthly": mon, "monthly_workbook": mon_wb,
    }
    return person, rows


def collect_issues(roster, snaps, people, report_by_slug):
    """What still needs the maintainer or an outside limit to clear. Every item names who is affected and what to do."""
    status = load_json(STATUS, {})
    by_slug = {p["slug"]: p for p in people}
    out = []

    def item(group, title, detail, who=(), action="", severity="todo", rows=()):
        out.append({"group": group, "title": title, "detail": detail, "action": action, "severity": severity, "rows": list(rows),
                    "who": [{"slug": s, "name": n, "linked": s in by_slug} for s, n in who]})

    if "openalex_budget" in status:
        s = status["openalex_budget"]
        item("blocked", "OpenAlex budget used up", f"{s['message']} (first seen {s['since']}). Nothing new can be fetched until then.",
             action="Set OPENALEX_API_KEY in the shell that runs the pipeline (the key is read from the environment, never stored), then: make snapshot",
             severity="blocked")
    missing = [r for r in roster if r["slug"] not in by_slug]
    if missing:
        item("decide", f"{len(missing)} people have no OpenAlex paper printed with an NICT affiliation",
             "OpenAlex has no work on which their name appears together with NICT. Common causes: a different romanisation of the "
             "name, a name only in kanji, papers printed under another affiliation, or papers not yet indexed.",
             who=[(r["slug"], r["name"]) for r in missing],
             action="Send an OpenAlex author ID or ORCID, or another spelling of the name (aliases in roster.csv), then make snapshot.")
    prov = [(r, snaps[r["slug"]]) for r in roster if r["slug"] in by_slug and snaps.get(r["slug"], {}).get("source") == "openalex"
            and snaps[r["slug"]].get("author_ids") and not snaps[r["slug"]].get("ids_confirmed")]
    if prov:
        rows = []
        for r, s in prov:
            ps = ", ".join(f"{a['id']} ({a['name']}: {a['works']} works, {a['cited_by']:,} cited"
                           f"{'; ' + '; '.join(a['institutions']) if a['institutions'] else ''})" for a in s.get("author_profiles", []))
            rows.append(f"{r['name']}: {len(s['papers'])} papers from {len(s['author_ids'])} author ID(s): {ps}")
        item("check", f"{len(prov)} people rest on provisional OpenAlex author IDs",
             "No ID is confirmed in roster.csv, so the IDs are those OpenAlex attached to the person's name on works printing NICT, and all their works are "
             "counted. OpenAlex merges namesakes and splits one person over profiles, so the counts may include another person's papers or miss some.",
             who=[(r["slug"], r["name"]) for r, _ in prov], rows=rows,
             action="Check each person's IDs against their ORCID or homepage, then put the right ones (`;`-separated) into roster.csv openalex_ids "
                    "(or send me the ORCID) and run make snapshot.")
    ex = [r for r in roster if "ex-nict" in (r.get("notes") or "").lower() and r["slug"] in by_slug]
    if ex:
        item("info", "People who left NICT",
             "Only papers printed with an NICT affiliation count, which limits them to their time at NICT without setting years. "
             "A paper written at NICT but printed under another affiliation is not counted.",
             who=[(r["slug"], r["name"]) for r in ex])
    unclass = [(s, f"{s} ({n})") for s, n in report_by_slug.items() if n]
    if unclass:
        item("check", "Venues the matcher could not classify",
             "Counted papers whose venue is neither a journal in SCImago nor a conference in CORE, nor a preprint or patent. They sit in 'Other'.",
             who=unclass, action="Add rows to backend/venue_overrides.csv (venue, kind, quartile, core_rank).")
    selfrep = sorted({r["slug"] for r in read_csv(SELF_REPORTED)})
    if selfrep:
        item("info", "Papers confirmed by the person's own page (unofficial)",
             "They are listed in self_reported.csv and counted with no citation figure, until a record appears in OpenAlex.",
             who=[(s, by_slug[s]["name"] if s in by_slug else s) for s in selfrep])
    item("info", "What the figures are",
             "Source: OpenAlex only. A paper counts for a person when OpenAlex prints the person's name on it together with an NICT affiliation; "
             "its citations are OpenAlex's. OpenAlex indexes fewer papers than Google Scholar, so totals are lower than Scholar's. "
             "There is no claimed-versus-counted comparison, as no profile totals are used. Google Scholar, Researchmap and ORCID "
             "data are kept in the snapshot but not used.")
    return out


def main():
    scholar = load_json(SCHOLAR, {})
    cache = load_json(OPENALEX, {"works_by_author": {}, "titles": {}})
    overrides = {(r["slug"], r["key"]): r for r in read_csv(PAPER_OVERRIDES)}
    xlsx, history = read_csv(XLSX_HISTORY), read_csv(HISTORY)
    self_rows = read_csv(SELF_REPORTED) + read_csv(SCHOLAR_PREPRINTS)
    monthly_raw = load_json(RAW / "monthly.json", {})
    profile_checks_all = load_json(BACKEND_DIR / "profile_checks.json", {})
    report, people, paper_files = [], [], {}
    waiting = []
    for p in load_roster():
        snap = scholar.get(p["slug"])
        if not snap or snap.get("source", "scholar") not in ACTIVE_SOURCES or not snap.get("papers"):
            waiting.append(f"{p['name']}: not found in OpenAlex" + (" (maintainer)" if "not found (maintainer" in p["notes"].lower() else ""))
            continue
        person, rows = build_person(p, snap, cache, overrides, xlsx, history, report, self_rows)
        mrec = monthly_raw.get(p["slug"], {})
        person["monthly"], person["monthly_citing"] = mrec.get("months", {}), mrec.get("citing", 0)
        person["monthly_workbook"] = {}
        c = profile_checks_all.get(p["slug"])
        person["scholar"] = None if not c else {
            "claimed": c["claimed"], "cleaned": c.get("cleaned", c["named_cites"]), "papers": c["papers"], "named_papers": c["named_papers"],
            "h": c["named_h"], "claimed_h": c["claimed_h"], "i10": c["named_i10"], "off_field": c["off_field_cites"],
            "not_named": c["not_named_cites"], "unknown": c["unknown_cites"], "fetched": c["fetched"],
            "share": round(c.get("cleaned", c["named_cites"]) / c["claimed"], 3) if c["claimed"] else None,
            "by_year": c.get("cleaned_by_year"), "years_method": c.get("years_method", ""),
            "since": (sum(v for y, v in c["cleaned_by_year"].items() if int(y) >= FROM_YEAR) if c.get("cleaned_by_year") else None)}
        people.append(person)
        paper_files[p["slug"]] = rows
        if person["unconfirmed"]["papers"]:
            report.append(f"{p['slug']}: {person['unconfirmed']['papers']} unconfirmed papers (cut author lists; run fetch_scholar.py --details --only {p['slug']})")
    for r in people:
        s = r.get("scholar")
        has_year = bool(s and s.get("since") is not None)
        papers_main = s["named_papers"] if s else r["counted"]["papers"]
        r["main"] = {"citations": s["cleaned"] if s else r["counted"]["citations"], "source": "scholar" if s else "openalex",
                     "papers": papers_main, "score": round((s["cleaned"] if s else r["counted"]["citations"]) / papers_main, 2) if papers_main else 0.0,
                     "score_since": round(r["since_window"]["citations"] / r["since_window"]["papers"], 2) if r["since_window"]["papers"] else 0.0,
                     "since": s["since"] if has_year else r["received_since"], "since_source": "scholar" if has_year else "openalex"}
    people.sort(key=lambda r: (-r["main"]["citations"], -r["counted"]["citations"], r["name"]))   # Scholar cleaned, else OpenAlex

    # overview
    sum_ = lambda f: sum(f(r) for r in people)
    total_by_month = collections.Counter()
    for r in people:
        for m, n in r["monthly"].items():
            total_by_month[m] += n
    months = sorted(total_by_month)
    cohort = [r for r in people if r["monthly"]]
    total_by_month = dict(sorted(total_by_month.items()))
    venues_all = {k: sum_(lambda r: r["venues"][k]) for k in VENUE_KEYS}
    venues_since = {k: sum_(lambda r: r["venues_since"][k]) for k in VENUE_KEYS}
    by_year = collections.Counter()
    for r in people:
        for y, v in r["by_year"].items():
            by_year[y] += v
    overview = {
        "built": TODAY.isoformat(), "from_year": FROM_YEAR, "people": len(people), "source": "OpenAlex",
        "citations": sum_(lambda r: r["counted"]["citations"]), "papers": sum_(lambda r: r["counted"]["papers"]),
        "main_citations": sum_(lambda r: r["main"]["citations"]), "main_scholar_people": sum_(lambda r: 1 if r["main"]["source"] == "scholar" else 0),
        "received_since": sum_(lambda r: r["received_since"]),
        "papers_since": sum_(lambda r: r["since_window"]["papers"]), "citations_papers_since": sum_(lambda r: r["since_window"]["citations"]),
        "top_papers": sum_(lambda r: r["venues"]["conf_astar"] + r["venues"]["journal_q1"]),
        "top_papers_since": sum_(lambda r: r["venues_since"]["conf_astar"] + r["venues_since"]["journal_q1"]),
        "venues": venues_all, "venues_since": venues_since, "by_year": dict(sorted(by_year.items())), "scholar_years_people": sum(1 for r in people if (r.get("scholar") or {}).get("by_year")),
        "months": months, "cohort": [r["slug"] for r in cohort], "total_by_month": total_by_month,
        "waiting": waiting,
    }

    # charts (inline SVG)
    seg = [("since", "s1", f"Received since {FROM_YEAR}"), ("before", "old", f"Received before {FROM_YEAR}")]
    rows_c = [(r["name"], f"people/{r['slug']}/", {"since": r["received_since"], "before": max(r["counted"]["citations"] - r["received_since"], 0)})
              for r in sorted(people, key=lambda r: (-r["received_since"], -r["counted"]["citations"], r["name"]))]  # by received since 2021
    # conferences in hot colours (h0 A* .. h3 C), journals in cold ones (c0 Q1 .. c3 Q4); grey where there is no rank
    jq = [("journal_q1", "c0", "Q1"), ("journal_q2", "c1", "Q2"), ("journal_q3", "c2", "Q3"), ("journal_q4", "c3", "Q4"),
          ("journal_other", "n", "Journal, not in SCImago")]
    cr = [("conf_astar", "h0", "A*"), ("conf_a", "h1", "A"), ("conf_b", "h2", "B"), ("conf_c", "h3", "C"), ("conf_unranked", "n", "Unranked")]

    def pie_for(v):
        oc = v["conf_c"] + v["conf_unranked"]
        oj = v["journal_q2"] + v["journal_q3"] + v["journal_q4"] + v["journal_other"]
        rest = v["preprint"] + v["patent"] + v["other"]
        return charts.pie([("Conf. A*", "h0", v["conf_astar"]), ("Conf. A", "h1", v["conf_a"]), ("Conf. B", "h2", v["conf_b"]),
                           ("Other conferences", "h3", oc), ("Journal Q1", "c0", v["journal_q1"]), ("Other journals", "c2", oj),
                           ("Preprints, patents, other", "n", rest)])

    scholar_year_total = collections.Counter()
    for r in people:
        for y, v in ((r.get('scholar') or {}).get('by_year') or {}).items():
            scholar_year_total[y] += v
    scholar_year_total = dict(scholar_year_total)
    n_scholar_years = sum(1 for r in people if (r.get('scholar') or {}).get('by_year'))

    def year_points(by_year, first=2010):
        pts = []
        for y in range(first, TODAY.year + 1):
            pts.append((f"{y}*" if y == TODAY.year else str(y), by_year.get(str(y), 0)))
        return pts

    ch = {
        "citations": charts.stacked_h(rows_c, seg, sort_total=False),
        "citations_legend": charts.legend([(c, n) for _, c, n in seg]),
        "years": charts.bars_v(year_points(overview["by_year"]), from_x=str(FROM_YEAR)),
        "journals": charts.stacked_h([(r["name"], f"people/{r['slug']}/", r["venues"]) for r in people], jq),
        "journals_legend": charts.legend([(c, n) for _, c, n in jq]),
        "conferences": charts.stacked_h([(r["name"], f"people/{r['slug']}/", r["venues"]) for r in people], cr),
        "conferences_legend": charts.legend([(c, n) for _, c, n in cr]),
        "journals_since": charts.stacked_h([(r["name"], f"people/{r['slug']}/", r["venues_since"]) for r in people], jq),
        "conferences_since": charts.stacked_h([(r["name"], f"people/{r['slug']}/", r["venues_since"]) for r in people], cr),
        "years_group": charts.bars_v(year_points(scholar_year_total), width=760, height=220, from_x=str(FROM_YEAR)) if scholar_year_total else "",
        "years_people": {r["slug"]: charts.bars_v(year_points((r.get("scholar") or {}).get("by_year") or r["by_year"]), width=560, height=170,
                                                  from_x=str(FROM_YEAR))
                         for r in people if (r.get("scholar") or {}).get("by_year") or r["by_year"]},
        "years_source": {r["slug"]: ("scholar" if (r.get("scholar") or {}).get("by_year") else "openalex") for r in people},
        "person_pie": {r["slug"]: {"all": pie_for(r["venues"]), "since": pie_for(r["venues_since"])} for r in people},
        "person_pie": {r["slug"]: {"all": pie_for(r["venues"]), "since": pie_for(r["venues_since"])} for r in people},
        "person_years": {r["slug"]: charts.bars_v(year_points(r["by_year"]), from_x=str(FROM_YEAR))
                         for r in people if r["by_year"]},
    }

    unclassified = collections.Counter(line.split(":", 1)[0] for line in report if "venue not classified" in line)
    roster_all = load_roster()
    issues = collect_issues(roster_all, scholar, people, unclassified)

    # cooperation (co-authors), from the papers' OpenAlex author lists
    names = {r["slug"]: r["name"] for r in people}
    links = {s: f"../people/{s}/" for s in names}
    col = cooperation.collect(scholar, [{"slug": r["slug"], "name": r["name"]} for r in people])
    co_rows, co_inst, co_ctry = cooperation.tables(col, names)
    int_svg, isolated = cooperation.svg_internal(col, names, links)
    ext_by_id = {a: x for a, x in col["ext"].items()}
    for r in people:
        pp = col["per_person"].get(r["slug"], {"works": 0, "ext": {}, "internal": {}})
        top = sorted(pp["ext"].items(), key=lambda kv: (-kv[1], ext_by_id[kv[0]]["name"]))[:6]
        r["coauthors_n"] = len(pp["ext"])
        r["coauthors_top"] = [{"name": ext_by_id[a]["name"], "papers": n,
                               "inst": (ext_by_id[a]["inst"].most_common(1) or [("", 0)])[0][0],
                               "country": (ext_by_id[a]["country"].most_common(1) or [("", 0)])[0][0]} for a, n in top]
        r["internal_top"] = [{"slug": s, "name": names.get(s, s), "papers": n} for s, n in
                             sorted(pp["internal"].items(), key=lambda kv: -kv[1])[:6]]
    pairs = sorted(col["pair"].items(), key=lambda kv: -kv[1])[:25]
    cooperation_data = {
        "tracked": len(people), "works": len(col["works"]), "ext_total": len(col["ext"]),
        "ext_repeat": sum(1 for x in col["ext"].values() if len(x["works"]) >= 2),
        "ext_nict": sum(1 for x in col["ext"].values() if "Information and Communications Technology" in ((x["inst"].most_common(1) or [("", 0)])[0][0])),
        "internal_pairs": len(col["pair"]), "internal_works": sum(1 for e in col["works"].values() if len(e["tracked"]) > 1),
        "internal_svg": int_svg, "external_svg": cooperation.svg_external(col, names, links, co_rows),
        "isolated": [{"slug": s, "name": names[s]} for s in isolated],
        "pairs": [{"a": a, "b": b, "a_name": names[a], "b_name": names[b], "papers": n} for (a, b), n in pairs],
        "coauthors": co_rows, "institutions": co_inst, "countries": co_ctry, "max_authors": cooperation.MAX_AUTHORS,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    save_json(DATA / "cooperation.json", cooperation_data)
    pc = load_json(BACKEND_DIR / "profile_checks.json", {})
    save_json(DATA / "profile_checks.json", {s: v for s, v in pc.items() if s in {r["slug"] for r in people}})
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
    (CONTENT / "_index.md").write_text('---\ntitle: "People"\nbuild:\n  render: never\n---\n', encoding="utf-8")
    for r in people:
        (CONTENT / f"{r['slug']}.md").write_text(f'---\ntitle: "{r["name"]}"\nslug: "{r["slug"]}"\nname_ja: "{r["name_ja"]}"\n---\n', encoding="utf-8")
    WORK.mkdir(exist_ok=True)
    (WORK / "build_report.txt").write_text("\n".join(waiting + report) + "\n", encoding="utf-8")
    print(f"{len(people)} people, {overview['papers']:,} papers, {overview['citations']:,} citations "
          f"({overview['received_since']:,} received since {FROM_YEAR}), {overview['top_papers']} A*/Q1 papers; "
          f"{len(waiting)} without data, {len(report)} notes")


if __name__ == "__main__":
    main()
