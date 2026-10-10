"""Read the screening workbook (stdlib only) into roster.csv, xlsx_history.csv and scholar_links.md.

roster.csv is hand-kept after the first run: this script only adds people it has not seen.
"""
import csv, re, sys, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
XLSX = HERE.parent / "Google Scholar_WSL_202607.xlsx"
NOTES = {
    "村井 英志": "Workbook note: counts co-authored papers and patents.",
    "Eum Suyong": "Workbook note: profile registered on the day of the 2026/07 snapshot.",
}


def col(ref):
    return re.match(r"[A-Z]+", ref).group(0)


def read_sheets(path):
    z = zipfile.ZipFile(path)
    ss = [re.sub(r"<[^>]+>", "", s) for s in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    wb = z.read("xl/workbook.xml").decode()
    rels = dict(re.findall(r'<Relationship Id="(rId\d+)"[^>]*Target="([^"]+)"', z.read("xl/_rels/workbook.xml.rels").decode()))
    rels.update({k: v for v, k in re.findall(r'Target="([^"]+)"[^>]*Id="(rId\d+)"', z.read("xl/_rels/workbook.xml.rels").decode())})
    out = {}
    for name, rid in re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb):
        x = z.read("xl/" + rels[rid]).decode()
        grid = {}
        for rno, row in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', x, re.S):
            for ref, attr, inner in re.findall(r'<c r="([A-Z]+\d+)"([^>]*?)(?:/>|>(.*?)</c>)', row, re.S):
                v = re.search(r"<v>(.*?)</v>", inner or "")
                if not v:
                    continue
                val = v.group(1)
                if 't="s"' in attr:
                    val = ss[int(val)]
                grid[ref] = val.replace("&amp;", "&")
        out[name] = grid
    return out


def clean_ja(s):
    # names carry furigana appended in the same cell: keep the part before katakana.
    m = re.match(r"^(.*?[一-鿿]+)\s*[゠-ヿ]+$", s.strip())
    return (m.group(1) if m else s).strip().replace("　", " ")


def main():
    sheets = read_sheets(XLSX)
    total = sheets["Total citation"]
    people = []
    for r in range(4, 24):
        ja = total.get(f"A{r}")
        if not ja:
            continue
        search = (total.get(f"B{r}") or "").replace(" nict", "").strip()
        note = next((v for k, v in NOTES.items() if ja.startswith(k)), "")
        people.append({"row": r, "name_ja": clean_ja(ja), "search_name": search, "note": note})

    def slug(p):
        base = p["search_name"] or p["name_ja"]
        s = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
        return s or f"row-{p['row']}"

    roster = HERE / "roster.csv"
    have = {}
    if roster.exists():
        have = {r["row"]: r for r in csv.DictReader(roster.open(encoding="utf-8"))}
    fields = ["row", "slug", "name", "name_ja", "aliases", "scholar_id", "researchmap_id", "orcid", "homepage", "openalex_ids", "approved", "notes", "period_from", "period_to"]
    with roster.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        for p in people:
            old = have.get(str(p["row"]), {})
            note = old.get("notes") or p["note"] or ("No search name in the workbook." if not p["search_name"] else "")
            w.writerow({
                "row": p["row"], "slug": old.get("slug") or slug(p),
                "name": old.get("name") or p["search_name"] or p["name_ja"],
                "name_ja": p["name_ja"], "aliases": old.get("aliases", ""), "scholar_id": old.get("scholar_id", ""), "researchmap_id": old.get("researchmap_id", ""), "orcid": old.get("orcid", ""), "homepage": old.get("homepage", ""),
                "openalex_ids": old.get("openalex_ids", ""), "approved": old.get("approved") or "yes", "notes": note,
                "period_from": old.get("period_from", ""), "period_to": old.get("period_to", "")})
    # people added by hand with add_profile.py (not in the workbook) are kept
    keep = [r for r in have.values() if r["row"].startswith("x")]
    if keep:
        with roster.open("a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fields).writerows(keep)
    # the one profile link stored in the workbook
    link = re.search(r"user=([A-Za-z0-9_-]{12})", zipfile.ZipFile(XLSX).read("xl/worksheets/_rels/sheet1.xml.rels").decode())
    if link:
        rows = list(csv.DictReader(roster.open(encoding="utf-8")))
        for r in rows:
            if r["row"] == "18" and not r["scholar_id"]:
                r["scholar_id"] = link.group(1)
        with roster.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fields); w.writeheader(); w.writerows(rows)

    # monthly history of every sheet (hidden ones included)
    with (HERE / "xlsx_history.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["row", "sheet", "month", "value"])
        for name, g in sheets.items():
            hdr = {col(k): v for k, v in g.items() if re.fullmatch(r"[A-Z]+3", k) and re.fullmatch(r"\d{4}/\d{2}", v)}
            for p in people:
                for c, month in hdr.items():
                    v = g.get(f"{c}{p['row']}")
                    if v not in (None, ""):
                        w.writerow([p["row"], name, month.replace("/", "-"), v])

    rows = list(csv.DictReader(roster.open(encoding="utf-8")))
    md = ["# Google Scholar profile links", "",
          "Fill in the **Scholar link** column with each person's profile URL "
          "(`https://scholar.google.com/citations?user=...`). Leave it empty if there is no profile.",
          "Then tell Claude to read this file (`backend/scholar_links.md`).", "",
          "| # | Name | 日本語 | Scholar link | Find on Scholar | Note |", "|---|---|---|---|---|---|"]
    for r in rows:
        url = f"https://scholar.google.com/citations?user={r['scholar_id']}" if r["scholar_id"] else ""
        q = (r['name'] + " nict").replace(" ", "+")
        find = f"[search](https://scholar.google.com/citations?view_op=search_authors&mauthors={q}&hl=en)"
        md.append(f"| {r['row']} | {r['name']} | {r['name_ja']} | {url} | {find} | {r['notes']} |")
    (HERE / "scholar_links.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{len(rows)} people; history rows written")


if __name__ == "__main__":
    main()
