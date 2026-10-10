"""Classify a venue string: journal (SJR quartile), conference (CORE rank), preprint, patent or other.

Pure functions over the two downloaded tables (see fetch_rankings.py) and the hand-kept venue_overrides.csv
(columns: venue, kind, quartile, core_rank, note), so every decision can be tested and overridden.
"""
import csv
import re
from functools import lru_cache

from common import RAW, VENUE_OVERRIDES, fold, read_csv, venue_core

STOP = set("proceedings of the on in and for a an international annual conference workshop symposium ieee acm "
           "joint first second third th st nd rd".split())
CONF_WORDS = re.compile(r"\b(conference|symposium|workshop|congress|proceedings|meeting|colloquium|summit|forum|"
                        r"convention|conf|symp|wksp|ieee .* (?:icc|globecom))\b", re.I)
JOURNAL_WORDS = re.compile(r"\b(journal|transactions|trans|letters|magazine|review|reviews|access|bulletin|"
                           r"annals|communications|applied sciences|sensors|electronics|remote sensing)\b", re.I)
PREPRINT = re.compile(r"arxiv|preprint|ssrn|researchsquare|techrxiv|biorxiv|hal\b", re.I)
PATENT = re.compile(r"\bpatent\b|^US\s?\d|^JP\s?\d|^WO\s?\d|^EP\s?\d|特許", re.I)
OTHER = re.compile(r"thesis|dissertation|technical report|white paper|book|chapter|ph\.?d|master", re.I)
RANK_MAP = {"A*": "A*", "A": "A", "B": "B", "C": "C"}  # Australasian and national ranks count as unranked


def core_rank(rank):
    return RANK_MAP.get(rank.strip(), "Unranked")


@lru_cache(maxsize=1)
def tables(sjr_file=None):
    """CORE editions are read newest first (ICORE2026, CORE2023, ...): a conference keeps its newest rank."""
    sjr_file = sjr_file or max(RAW.glob("sjr_*.csv"), default=None)
    core, acr, seen = [], {}, set()
    for core_file in sorted(RAW.glob("core_*.csv"), reverse=True):
        for r in csv.reader(open(core_file, encoding="utf-8", errors="ignore")):
            if len(r) < 5:
                continue
            name, acronym, rank = r[1].strip(), r[2].strip(), core_rank(r[4])
            if fold(name) in seen:
                continue
            seen.add(fold(name))
            core.append((fold(name), name, acronym, rank))
            if acronym and len(acronym) >= 3:
                acr.setdefault(acronym.lower(), []).append((fold(name), rank))
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
    return {"core": core, "acr": acr, "sjr": sjr, "issn": issn}


def sig(s):
    return {t for t in fold(s).split() if t not in STOP and not re.fullmatch(r"\d+(st|nd|rd|th)?|\d{2,4}", t)}


def lookup_core(venue):
    t = tables()
    f = " " + fold(venue_core(venue)) + " "
    best = None
    for key, name, acronym, rank in t["core"]:
        if len(key) > 12 and f" {key} " in f:  # the full CORE name is printed
            if best is None or len(key) > len(best[0]):
                best = (key, name, rank)
    if best:
        return best[1], best[2]
    words = sig(venue)
    # an acronym printed in the line, confirmed by most of the conference's own words
    for a in set(re.findall(r"\(([A-Za-z][A-Za-z0-9\-]{2,12})\)", venue)) | set(re.findall(r"\b([A-Z][A-Za-z]{2,10}|[A-Z0-9\-]{3,10})\b", venue)):
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


def classify(venue, issns=(), oa_type=None):
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
        return {"kind": "preprint", "quartile": "", "core_rank": "", "matched": "", "how": "pattern"}
    looks_conf = bool(CONF_WORDS.search(v)) or oa_type == "conference"
    j = lookup_journal(v, issns, fuzzy=not looks_conf)
    if j:
        return {"kind": "journal", "quartile": j[1], "core_rank": "", "matched": j[0], "how": "SJR"}
    c = lookup_core(v)
    if c and (looks_conf or not JOURNAL_WORDS.search(v)):
        return {"kind": "conference", "quartile": "", "core_rank": c[1], "matched": c[0], "how": "CORE"}
    if looks_conf:
        return {"kind": "conference", "quartile": "", "core_rank": "Unranked", "matched": "", "how": "not in CORE"}
    if OTHER.search(v):
        return {"kind": "other", "quartile": "", "core_rank": "", "matched": "", "how": "pattern"}
    if JOURNAL_WORDS.search(v):
        return {"kind": "journal", "quartile": "", "core_rank": "", "matched": "", "how": "not in SJR"}
    return {"kind": "unknown", "quartile": "", "core_rank": "", "matched": "", "how": "no match"}
