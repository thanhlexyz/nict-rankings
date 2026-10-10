"""Researcher cooperation from OpenAlex: who the tracked researchers write papers with.

Pure functions over the snapshots (scholar.json, source openalex, papers carry `coauthors`). A work is counted once however many
tracked researchers are on it. Two layouts are drawn here, once, as SVG (a seeded force simulation, like the template's
graphs): the tracked researchers among themselves, and the tracked researchers with their most frequent outside co-authors.
"""
import collections
import itertools
import math
import random
from html import escape

W, H = 1000, 720
MAX_AUTHORS = 30    # a work with more authors is a consortium paper: it says little about who cooperates with whom


def collect(snaps, people):
    """people: [{"slug","name"}]. -> dict with works, per-person data and the aggregated co-author tables."""
    idmap = {}
    for p in people:
        for aid in snaps.get(p["slug"], {}).get("author_ids", []):
            idmap[aid] = p["slug"]
    works = {}
    for p in people:
        for x in snaps.get(p["slug"], {}).get("papers", []):
            w = x.get("openalex")
            ca = x.get("coauthors") or []
            if not w or not ca or len(ca) > MAX_AUTHORS:
                continue
            e = works.setdefault(w, {"title": x["title"], "year": x["year"], "authors": ca, "tracked": set()})
            e["tracked"].add(p["slug"])
    for e in works.values():   # a tracked person may be on the work without their snapshot listing it (another ID of theirs)
        for a in e["authors"]:
            if a["id"] in idmap:
                e["tracked"].add(idmap[a["id"]])
    tracked_ids = set(idmap)
    pair = collections.Counter()
    ext = {}
    per_person = collections.defaultdict(lambda: {"works": 0, "ext": collections.Counter(), "internal": collections.Counter()})
    for wid, e in works.items():
        t = sorted(e["tracked"])
        for s in t:
            per_person[s]["works"] += 1
        for a, b in itertools.combinations(t, 2):
            pair[(a, b)] += 1
            per_person[a]["internal"][b] += 1
            per_person[b]["internal"][a] += 1
        for a in e["authors"]:
            if not a["id"] or a["id"] in tracked_ids:
                continue
            x = ext.setdefault(a["id"], {"id": a["id"], "name": a["name"], "works": set(), "tracked": collections.Counter(),
                                          "inst": collections.Counter(), "country": collections.Counter(), "years": []})
            x["works"].add(wid)
            for s in t:
                x["tracked"][s] += 1
                per_person[s]["ext"][a["id"]] += 1
            if a["inst"]:
                x["inst"][a["inst"]] += 1
            if a["country"]:
                x["country"][a["country"]] += 1
            if e["year"]:
                x["years"].append(e["year"])
    # one person OpenAlex split over name orders ("Harada Hiroshi" / "Hiroshi Harada") counts once
    from common import fold
    merged = {}
    for aid, x in ext.items():
        key = tuple(sorted(fold(x["name"]).split())) if len(fold(x["name"]).split()) >= 2 else ("id", aid)
        m = merged.get(key)
        if m is None:
            merged[key] = x
            continue
        m["works"] |= x["works"]
        m["tracked"].update(x["tracked"])
        m["inst"].update(x["inst"])
        m["country"].update(x["country"])
        m["years"] += x["years"]
        for s, n in x["tracked"].items():
            per_person[s]["ext"][m["id"]] += n
            del per_person[s]["ext"][aid]
    ext = {x["id"]: x for x in merged.values()}
    return {"works": works, "pair": pair, "ext": ext, "per_person": per_person, "idmap": idmap}


def tables(col, names, top_ext=60):
    ext = sorted(col["ext"].values(), key=lambda x: (-len(x["works"]), -len(x["tracked"]), x["name"]))
    rows = []
    for x in ext[:top_ext]:
        inst_top = (x["inst"].most_common(1) or [("", 0)])[0][0]
        rows.append({"id": x["id"], "name": x["name"], "papers": len(x["works"]), "nict": "Information and Communications Technology" in inst_top,
                     "inst": (x["inst"].most_common(1) or [("", 0)])[0][0], "country": (x["country"].most_common(1) or [("", 0)])[0][0],
                     "with": [{"slug": s, "name": names.get(s, s), "papers": n} for s, n in x["tracked"].most_common()],
                     "first": min(x["years"]) if x["years"] else None, "last": max(x["years"]) if x["years"] else None})
    inst = collections.defaultdict(lambda: {"works": set(), "people": set()})
    ctry = collections.defaultdict(lambda: {"works": set(), "people": set()})
    for x in col["ext"].values():
        i = (x["inst"].most_common(1) or [("", 0)])[0][0]
        c = (x["country"].most_common(1) or [("", 0)])[0][0]
        if i:
            inst[i]["works"] |= x["works"]; inst[i]["people"].add(x["id"])
        if c:
            ctry[c]["works"] |= x["works"]; ctry[c]["people"].add(x["id"])
    mk = lambda d, n: [{"name": k, "papers": len(v["works"]), "coauthors": len(v["people"])}
                       for k, v in sorted(d.items(), key=lambda kv: (-len(kv[1]["works"]), kv[0]))[:n]]
    return rows, mk(inst, 25), mk(ctry, 20)


def force(ids, edges, k=95, seed=7, steps=500):
    """Fruchterman-Reingold on one graph; a line pulls in proportion to w**0.8, so heavy pairs settle close."""
    rng = random.Random(seed)
    n = len(ids)
    pos = {i: [math.cos(2 * math.pi * j / n) * 150 + rng.uniform(-4, 4), math.sin(2 * math.pi * j / n) * 150 + rng.uniform(-4, 4)]
           for j, i in enumerate(sorted(ids))}
    temp = 4 * k
    for _ in range(steps):
        disp = {i: [0.0, 0.0] for i in pos}
        for a, b in itertools.combinations(pos, 2):
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            d = max(math.hypot(dx, dy), 0.01)
            f = k * k / d
            disp[a][0] += dx / d * f; disp[a][1] += dy / d * f
            disp[b][0] -= dx / d * f; disp[b][1] -= dy / d * f
        for (a, b), w in edges.items():
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            d = max(math.hypot(dx, dy), 0.01)
            f = d * d / k * (w ** 0.8) * 0.35
            disp[a][0] -= dx / d * f; disp[a][1] -= dy / d * f
            disp[b][0] += dx / d * f; disp[b][1] += dy / d * f
        for i in pos:
            d = max(math.hypot(*disp[i]), 0.01)
            m = min(d, temp)
            pos[i][0] += disp[i][0] / d * m
            pos[i][1] += disp[i][1] / d * m
        temp *= 0.992
    xs = [p[0] for p in pos.values()]; ys = [p[1] for p in pos.values()]
    sx = (W - 260) / max(max(xs) - min(xs), 1); sy = (H - 140) / max(max(ys) - min(ys), 1)
    s = min(sx, sy)
    return {i: (130 + (p[0] - min(xs)) * s + (W - 260 - (max(xs) - min(xs)) * s) / 2,
                70 + (p[1] - min(ys)) * s + (H - 140 - (max(ys) - min(ys)) * s) / 2) for i, p in pos.items()}


def short(s, n=34):
    return s if len(s) <= n else s[: n - 1] + "…"


def svg_internal(col, names, links):
    """The tracked researchers among themselves. links: slug -> page URL."""
    edges = {k: v for k, v in col["pair"].items() if v > 0}
    ids = sorted({i for e in edges for i in e})
    if len(ids) < 2:
        return "", []
    pos = force(ids, edges)
    wmax = max(edges.values())
    papers = {s: col["per_person"][s]["works"] for s in ids}
    out = [f'<svg class="net" viewBox="0 0 {W} {H}" role="img" aria-label="cooperation among the tracked researchers">']
    for (a, b), w in sorted(edges.items(), key=lambda kv: kv[1]):
        (x1, y1), (x2, y2) = pos[a], pos[b]
        out.append(f'<line class="edge" data-a="{a}" data-b="{b}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                   f'stroke-width="{1 + 7 * (w / wmax) ** 0.7:.1f}"><title>{escape(names[a])} – {escape(names[b])}: {w} shared papers</title></line>')
    for (a, b), w in edges.items():
        if w >= 3:
            (x1, y1), (x2, y2) = pos[a], pos[b]
            out.append(f'<text class="ew" data-a="{a}" data-b="{b}" x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2 + 4:.1f}" text-anchor="middle">{w}</text>')
    pmax = max(papers.values())
    for s in ids:
        x, y = pos[s]
        r = 7 + 11 * (papers[s] / pmax) ** 0.5
        out.append(f'<a href="{links.get(s, "#")}" class="node" data-id="{s}"><circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}"/>'
                   f'<text x="{x:.1f}" y="{y + r + 14:.1f}" text-anchor="middle">{escape(names[s])}</text>'
                   f'<title>{escape(names[s])}: {papers[s]} papers, {sum(col["per_person"][s]["internal"].values())} shared with the others</title></a>')
    out.append("</svg>")
    isolated = [s for s in names if s not in ids]
    return "".join(out), isolated


def svg_external(col, names, links, rows, per=40):
    """Tracked researchers (left) and their most frequent outside co-authors (right), a line for each pair that shares papers."""
    right = [r for r in rows if r["papers"] >= 2][:per]
    if not right:
        return ""
    left_ids = sorted({w["slug"] for r in right for w in r["with"]}, key=lambda s: -col["per_person"][s]["works"])
    gap = 22
    h = max(len(right), len(left_ids)) * gap + 40
    ly = {s: 30 + i * (h - 60) / max(len(left_ids) - 1, 1) for i, s in enumerate(left_ids)}
    ry = {r["id"]: 30 + i * (h - 60) / max(len(right) - 1, 1) for i, r in enumerate(right)}
    lx, rx = 250, 640
    wmax = max(w["papers"] for r in right for w in r["with"])
    out = [f'<svg class="net ext" viewBox="0 0 1000 {h:.0f}" role="img" aria-label="outside co-authors of the tracked researchers">']
    for r in right:
        for w in r["with"]:
            if w["slug"] in ly:
                out.append(f'<line class="edge" data-a="{w["slug"]}" data-b="{r["id"]}" x1="{lx + 8}" y1="{ly[w["slug"]]:.1f}" x2="{rx - 8}" '
                           f'y2="{ry[r["id"]]:.1f}" stroke-width="{0.8 + 5 * (w["papers"] / wmax) ** 0.7:.1f}">'
                           f'<title>{escape(names[w["slug"]])} – {escape(r["name"])}: {w["papers"]} shared papers</title></line>')
    for s in left_ids:
        out.append(f'<a href="{links.get(s, "#")}" class="node t" data-id="{s}"><circle cx="{lx}" cy="{ly[s]:.1f}" r="7"/>'
                   f'<text x="{lx - 14}" y="{ly[s] + 4:.1f}" text-anchor="end">{escape(names[s])}</text></a>')
    for r in right:
        out.append(f'<g class="node {"c0" if r.get("nict") else "c1"}" data-id="{r["id"]}"><circle cx="{rx}" cy="{ry[r["id"]]:.1f}" r="{5 + min(r["papers"], 20) * 0.35:.1f}"/>'
                   f'<text x="{rx + 14}" y="{ry[r["id"]] + 4:.1f}">{escape(short(r["name"], 26))}'
                   f'<tspan class="sub"> {escape(r["country"])} · {escape(short(r["inst"], 30))}</tspan></text>'
                   f'<title>{escape(r["name"])} ({escape(r["inst"])} {escape(r["country"])}): {r["papers"]} papers with {len(r["with"])} tracked researchers</title></g>')
    out.append("</svg>")
    return "".join(out)
