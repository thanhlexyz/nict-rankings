"""Classify a venue string: journal (SJR quartile), conference (CORE rank), preprint, patent or other.

Pure functions over the two downloaded tables (see fetch_rankings.py) and the hand-kept venue_overrides.csv
(columns: venue, kind, quartile, core_rank, note), so every decision can be tested and overridden.
"""
import csv
import re
from pathlib import Path
from functools import lru_cache

from common import RAW, VENUE_OVERRIDES, fold, read_csv, venue_core

STOP = set("proceedings of the on in and for a an international annual conference workshop symposium ieee acm "
           "joint first second third th st nd rd".split())
CONF_WORDS = re.compile(r"\b(conference|symposium|workshop|congress|proceedings|meeting|colloquium|summit|forum|"
                        r"convention|conf|symp|wksp|ieee .* (?:icc|globecom))\b", re.I)
JOURNAL_WORDS = re.compile(r"\b(journal|transactions|trans|letters|magazine|review|reviews|access|bulletin|"
                           r"annals|communications|applied sciences|sensors|electronics|remote sensing)\b", re.I)
SIDE_EVENT = re.compile(r"\bwork\s?shops?\b|\bwksh?ps?\b|\bposters?\b|\bdemos?\b|\bdemonstrations?\b|\bcompanion\b|\badjunct\b|"
                        r"\bdoctoral (?:consortium|symposium)\b|\bstudent (?:research )?(?:competition|forum)\b|\bsatellite\b", re.I)
PREPRINT = re.compile(r"arxiv|preprint|ssrn|researchsquare|techrxiv|biorxiv|hal\b", re.I)
PATENT = re.compile(r"\bpatent\b|^US\s?\d|^JP\s?\d|^WO\s?\d|^EP\s?\d|特許", re.I)
OTHER = re.compile(r"thesis|dissertation|technical report|white paper|book|chapter|ph\.?d|master", re.I)
RANK_MAP = {"A*": "A*", "A": "A", "B": "B", "C": "C"}  # Australasian and national ranks count as unranked


def core_rank(rank):
    return RANK_MAP.get(rank.strip(), "Unranked")


def edition_year(path):
    m = re.search(r"(\d{4})", Path(path).stem)
    return int(m.group(1)) if m else 0


@lru_cache(maxsize=1)
def tables(sjr_file=None):
    """CORE by edition year ({2021: {core, acr}, ...}) and the SCImago table.

    A conference is looked up in the edition closest to the paper's year (the rank 'at the time'); see lookup_core.
    """
    sjr_file = sjr_file or max(RAW.glob("sjr_*.csv"), default=None)
    editions = {}
    for core_file in RAW.glob("core_*.csv"):
        core, acr = [], {}
        for r in csv.reader(open(core_file, encoding="utf-8", errors="ignore")):
            if len(r) < 5:
                continue
            name, acronym, rank = r[1].strip(), r[2].strip(), core_rank(r[4])
            acronym = re.sub(r"^(?:IEEE|ACM|IFIP|IEEE/ACM|IFIP/IEEE)\s+", "", acronym)  # "IEEE CCNC" is printed as "CCNC"
            name = re.sub(r"\s*\(.*\)\s*$", "", name).strip()  # "(was ESEC/FSE, changed 2024 ...)" is a database note
            core.append((fold(name), name, acronym, rank))
            if acronym and len(acronym) >= 3:
                acr.setdefault(acronym.lower(), []).append((fold(name), rank))
        editions[edition_year(core_file)] = {"core": core, "acr": acr, "file": Path(core_file).stem}
    sjr, issn = {}, {}
    if sjr_file:
        rd = csv.DictReader(open(sjr_file, encoding="utf-8", errors="ignore"), delimiter=";")
        for r in rd:
            q = r.get("SJR Best Quartile", "").strip()
            if not q.startswith("Q"):
                q = ""
            sjr.setdefault(fold(r["Title"]), (r["Title"], q))
            for i in re.split(r"[,\s]+", r.get("Issn", "")):
                if i:
                    issn[i[:4] + "-" + i[4:] if len(i) == 8 else i] = (r["Title"], q)
    return {"editions": editions, "sjr": sjr, "issn": issn}


def edition_order(year):
    """CORE editions to try for a paper of `year`, the rank 'at the time'.

    A list released in year E (CORE2021 in August 2021) governs conferences held after it, so a paper of year Y is
    looked up first in the newest edition earlier than Y (2021 -> CORE2020), then older ones, then later ones.
    A paper of the newest edition's year or later uses the newest edition.
    """
    ys = sorted(tables()["editions"])
    if not year or year >= ys[-1]:
        return ys[::-1]
    before = [y for y in ys if y < year][::-1]
    after = [y for y in ys if y >= year]
    return before + after


def sig(s):
    return {t for t in fold(s).split() if t not in STOP and not re.fullmatch(r"\d+(st|nd|rd|th)?|\d{2,4}", t)}


def plain(s):
    """Folded text without ordinals ('96 th', '19th') and years: they differ between editions of one conference."""
    f = fold(s.replace("&", " and "))
    f = re.sub(r"\b\d+\s*(?:st|nd|rd|th)\b", " ", f)
    f = re.sub(r"\b(?:19|20)\d{2}\b", " ", f)
    return re.sub(r"\s+", " ", f).strip()


def lookup_core(venue, year=None):
    for ed in edition_order(year):
        hit = _lookup_core_in(venue, tables()["editions"][ed])
        if hit:
            return hit[0], hit[1], tables()["editions"][ed]["file"]
    return None


def _lookup_core_in(venue, t):
    f = " " + plain(venue_core(venue)) + " "
    best = None
    for key, name, acronym, rank in t["core"]:
        if len(key) <= 12:
            continue
        bare = re.sub(r"^(?:ieee acm|ifip ieee|ieee ifip|ieee|acm|ifip) ", "", key)   # printed without the society prefix
        for k in (key, bare):
            if len(k) > 12 and f" {k} " in f:  # the full CORE name is printed
                if best is None or len(k) > len(best[0]):
                    best = (k, name, rank)
                break
    if best:
        return best[1], best[2]
    words = sig(plain(venue))
    # a short line that is just an acronym and a season or year ("VTC Fall'26"): a CORE acronym with one entry
    short = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]*", plain(venue_core(venue)) and venue_core(venue)) if w.lower() not in
             {"fall", "spring", "summer", "winter", "workshop", "conf", "conference", "proc", "proceedings"}]
    if 1 <= len(short) <= 2 and len(short[0]) >= 3 and len(t["acr"].get(short[0].lower(), [])) == 1:
        key, rank = t["acr"][short[0].lower()][0]
        return key, rank
    # an acronym printed in the line, confirmed by most of the conference's own words
    for a in set(re.findall(r"\(([A-Za-z][A-Za-z0-9\-]{2,12})\)", venue)) | set(re.findall(r"\b([A-Z0-9\-]{3,10}|[A-Za-z]*[A-Z][a-z]+[A-Z][A-Za-z]*)\b", venue)):
        for key, rank in t["acr"].get(a.lower(), []):
            cw = sig(key)
            share = len(cw & words) / len(cw) if cw else 0
            if share >= 0.7 or (len(a) >= 5 and share >= 0.5):
                return key, rank
    # no acronym needed when almost all words agree
    for key, name, acronym, rank in t["core"]:
        cw = sig(key)
        if len(cw) >= 3 and len(cw & words) / len(cw) >= 0.85 and len(words) <= len(cw) + 4:
            return name, rank
    return None


def lookup_journal(venue, issns=(), fuzzy=True):
    t = tables()
    for i in issns:
        if i in t["issn"]:
            return t["issn"][i]
    k = fold(venue_core(venue))
    if k in t["sjr"]:
        return t["sjr"][k]
    if not fuzzy:
        return None
    k2 = k.replace(" ieee ", " ").replace("trans ", "transactions ").replace("j ", "journal ")
    k2 = re.sub(r"^ieee ", "", k2)
    for key, v in t["sjr"].items():
        if re.sub(r"^ieee ", "", key) == k2 and len(k2) > 10:
            return v
    return None


@lru_cache(maxsize=1)
def overrides():
    return {fold(venue_core(r["venue"])): r for r in read_csv(VENUE_OVERRIDES)}


@lru_cache(maxsize=1)
def aliases():
    """venue_aliases.csv: another printed name of a conference -> the name CORE lists it under."""
    return {fold(r["alias"]): r["core_name"] for r in read_csv(RAW.parent / "venue_aliases.csv")}


def classify(venue, issns=(), oa_type=None, year=None):
    return dict(_classify(venue or "", tuple(issns or ()), oa_type, year))


@lru_cache(maxsize=None)
def _classify_cached(venue, issns, oa_type, year):
    return tuple(_classify_uncached(venue, issns, oa_type, year).items())


def _classify(venue, issns, oa_type, year):
    return _classify_cached(venue, issns, oa_type, year)


def _classify_uncached(venue, issns=(), oa_type=None, year=None):
    alias = aliases().get(fold(venue_core(venue or "")))
    if alias:  # classify under the name CORE uses
        c = _classify_uncached(alias, issns, oa_type, year)
        if c["kind"] == "conference":
            return {**c, "how": c["how"] + " (alias)"}
    """-> dict(kind, quartile, core_rank, matched, how). kind: journal|conference|preprint|patent|other|unknown."""
    v = venue_core(venue)
    o = overrides().get(fold(v))
    if o:
        return {"kind": o["kind"], "quartile": o.get("quartile") or "", "core_rank": o.get("core_rank") or "",
                "matched": o.get("venue") or v, "how": "override"}
    if not v:
        return {"kind": "unknown", "quartile": "", "core_rank": "", "matched": "", "how": "no venue"}
    if PATENT.search(venue):
        return {"kind": "patent", "quartile": "", "core_rank": "", "matched": "", "how": "pattern"}
    if PREPRINT.search(v):
        rest = re.sub(r"(?i)arxiv(?:\s+preprint)?\s*(?:arxiv)?\s*[:\s]*[a-z\-.]*\d[\d.]*(?:v\d+)?", " ", v)
        rest = re.sub(r"(?i)\b(?:preprint|arxiv)\b", " ", rest).strip(" ,;.")
        if rest and not PREPRINT.search(rest) and len(rest) > 2:
            c2 = _classify_uncached(rest, issns, oa_type, year)
            if c2["kind"] in ("conference", "journal") and c2["how"] in ("CORE", "SJR"):
                return {**c2, "how": c2["how"] + " (venue named on an arXiv entry)"}
        return {"kind": "preprint", "quartile": "", "core_rank": "", "matched": "", "how": "pattern"}
    looks_conf = bool(CONF_WORDS.search(v)) or oa_type == "conference" or bool(re.search(r"['’]\d{2}\b", venue))
    j = lookup_journal(v, issns, fuzzy=not looks_conf)
    if j:
        return {"kind": "journal", "quartile": j[1], "core_rank": "", "matched": j[0], "how": "SJR"}
    c = lookup_core(v, year)
    # a workshop, poster, demo or companion volume of a conference is not that conference's main track: it takes no rank from it
    if c and SIDE_EVENT.search(venue) and not re.search(r"workshop|symposium on|poster|demo", c[0], re.I):
        return {"kind": "conference", "quartile": "", "core_rank": "Unranked", "matched": "", "how": "workshop / side event of " + c[0]}
    if c and (looks_conf or not JOURNAL_WORDS.search(v)):
        return {"kind": "conference", "quartile": "", "core_rank": c[1], "matched": c[0], "how": "CORE", "edition": c[2]}
    if looks_conf:
        return {"kind": "conference", "quartile": "", "core_rank": "Unranked", "matched": "", "how": "not in CORE"}
    if OTHER.search(v):
        return {"kind": "other", "quartile": "", "core_rank": "", "matched": "", "how": "pattern"}
    if JOURNAL_WORDS.search(v):
        return {"kind": "journal", "quartile": "", "core_rank": "", "matched": "", "how": "not in SJR"}
    return {"kind": "unknown", "quartile": "", "core_rank": "", "matched": "", "how": "no match"}
