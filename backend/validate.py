"""Decide, per paper on a Scholar profile, whether it is the person's own. Pure functions (tests/).

Statuses (the About page states the same rules):
  verified     an independent record (OpenAlex) lists the person as an author, by author ID or by name
  listed       no such record, but the author list Scholar prints for the paper names the person
  unconfirmed  no independent record and Scholar prints a cut author list that does not show the person
  not_listed   the paper's author list (OpenAlex record, or Scholar's complete list) does not name the person
  self_reported the person's own page (self_reported.csv) lists the paper: counted, tagged unofficial
  outside      published outside the person's period at NICT (roster period_from / period_to); not counted
  maintainer   paper_overrides.csv says `yes` (counted) - or `no` (not_listed, reason from the note)
Counted ("confirmed") citations are verified + listed + maintainer-yes. Unconfirmed ones are shown, not counted.
"""
from common import authors_include, split_authors, title_key


def records_for(paper, person, cache):
    """OpenAlex records whose title equals the paper's (year within one), from the person's works and title lookups."""
    k = title_key(paper["title"])
    out = []
    for aid in person["openalex_ids"]:
        out += [w for w in cache["works_by_author"].get(aid, []) if title_key(w["title"]) == k]
    out += cache["titles"].get(k, [])
    seen, uniq = set(), []
    for w in out:
        if w["id"] in seen:
            continue
        seen.add(w["id"])
        if paper.get("year") and w.get("year") and abs(paper["year"] - w["year"]) > 1:
            continue
        uniq.append(w)
    return uniq


def record_names_person(rec, person):
    ids = set(person["openalex_ids"])
    for a in rec["authors"]:
        if a["id"] in ids or authors_include([a["name"], a["raw"]], person["names"]):
            return True
    return False


SOURCE_LABEL = {"scholar": "Scholar's", "researchmap": "Researchmap's", "orcid": "OpenAlex's (via ORCID)"}


def paper_status(paper, person, records, override=None, source="scholar"):
    """-> (status, reason)."""
    src = SOURCE_LABEL.get(source, "The source's")
    lo, hi = person.get("period_from") or None, person.get("period_to") or None
    year = paper.get("year")
    if (lo or hi) and not override and year and ((lo and year < int(lo)) or (hi and year > int(hi))):
        return "outside", f"Published in {year}, outside the period at NICT ({lo or '…'}–{hi or '…'})."
    if override:
        if override["decision"] == "yes":
            return "maintainer", override.get("note") or "Confirmed by the maintainer."
        return "not_listed", override.get("note") or "Decided by the maintainer."
    scholar_names = authors_include(split_authors(paper["authors"]), person["names"])
    if not paper["authors"].strip():
        return "unconfirmed", "No author list is available for this paper, and no independent record was found."
    if source == "openalex" and scholar_names:
        return "verified", "OpenAlex prints the person with an NICT affiliation on this paper."
    if any(record_names_person(r, person) for r in records):
        return "verified", "OpenAlex lists the person as an author."
    if scholar_names:
        if records:
            return "listed", f"{src} author list names the person; the OpenAlex record prints other names."
        return "listed", f"{src} author list names the person; no independent record was found."
    if records:
        return "not_listed", f"The OpenAlex record and {src} author list do not name the person."
    if not paper["authors_cut"]:
        return "not_listed", f"{src} complete author list does not name the person and no independent record was found."
    return "unconfirmed", f"{src} author list is cut and no independent record was found."


COUNTED = {"verified", "listed", "maintainer", "self_reported"}
