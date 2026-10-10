"""Inline SVG charts drawn at build time. Colours are CSS classes (style.css), so dark mode is a CSS matter.

Series slots follow the data-viz palette order: counted = s1 (blue), unconfirmed = s2 (orange), not listed = s3 (aqua).
Rank tiers are one blue ramp, t0 (strongest) .. t3, and t4 (grey) for unranked.
Every mark has a <title> (hover tooltip); each chart is followed by a table in the page for non-visual readers.
"""
from html import escape


def fmt(n):
    return f"{int(round(n)):,}"


def nice_max(v):
    if v <= 0:
        return 1
    mag = 10 ** (len(str(int(v))) - 1)
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag


def stacked_h(rows, segments, width=760, label_w=190, bar_h=16, gap=8, link=True, sort_total=True):
    """rows: [(label, href|None, {segment_key: value})]; segments: [(key, class, legend label)]."""
    if sort_total:
        rows = sorted(rows, key=lambda r: -sum(r[2].get(k, 0) for k, _, _ in segments))
    mx = nice_max(max([sum(r[2].get(k, 0) for k, _, _ in segments) for r in rows] + [1]))
    plot_w = width - label_w - 60
    h = len(rows) * (bar_h + gap) + 28
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" role="img" aria-label="stacked bars per person">']
    for i in range(0, 5):
        x = label_w + plot_w * i / 4
        out.append(f'<line class="grid" x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{h - 20}"/>'
                   f'<text class="axis" x="{x:.1f}" y="{h - 6}" text-anchor="middle">{fmt(mx * i / 4)}</text>')
    for r, (label, href, vals) in enumerate(rows):
        y = r * (bar_h + gap) + 4
        txt = f'<text class="lbl" x="{label_w - 8}" y="{y + bar_h - 4}" text-anchor="end">{escape(label)}</text>'
        out.append(f'<a href="{escape(href)}">{txt}</a>' if href and link else txt)
        x = label_w
        total = sum(vals.get(k, 0) for k, _, _ in segments)
        for key, cls, name in segments:
            v = vals.get(key, 0)
            if v <= 0:
                continue
            w = max(plot_w * v / mx, 1.5)
            out.append(f'<rect class="{cls}" x="{x:.1f}" y="{y}" width="{max(w - 2, 1):.1f}" height="{bar_h}" rx="2">'
                       f'<title>{escape(label)} · {escape(name)}: {fmt(v)}</title></rect>')
            x += w
        out.append(f'<text class="val" x="{x + 4:.1f}" y="{y + bar_h - 4}">{fmt(total)}</text>')
    out.append("</svg>")
    return "".join(out)


def legend(items):
    return '<ul class="legend">' + "".join(f'<li><span class="sw {c}"></span>{escape(n)}</li>' for c, n in items) + "</ul>"


def bars_v(points, width=560, height=190, from_x=None, unit="citations"):
    """points: [(x_label, value)]; bars from `from_x` on are the strong colour (the 'since 2021' window)."""
    if not points:
        return ""
    mx = nice_max(max(v for _, v in points))
    left, bottom = 44, 24
    pw, ph = width - left - 8, height - bottom - 8
    n = len(points)
    step = pw / n
    bw = min(step * 0.7, 28)
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(unit)} per year">']
    for i in range(0, 5):
        y = 8 + ph - ph * i / 4
        out.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - 8}" y2="{y:.1f}"/>'
                   f'<text class="axis" x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{fmt(mx * i / 4)}</text>')
    for i, (x, v) in enumerate(points):
        cx = left + step * i + step / 2
        bh = ph * v / mx
        cls = "s1" if (from_x is None or str(x) >= str(from_x)) else "old"
        out.append(f'<rect class="{cls}" x="{cx - bw / 2:.1f}" y="{8 + ph - bh:.1f}" width="{bw:.1f}" height="{max(bh, 0):.1f}" rx="2">'
                   f'<title>{escape(str(x))}: {fmt(v)} {escape(unit)}</title></rect>')
        if n <= 14 or i % 2 == 0:
            out.append(f'<text class="axis" x="{cx:.1f}" y="{height - 8}" text-anchor="middle">{escape(str(x))}</text>')
    out.append("</svg>")
    return "".join(out)


def lines(series, months, width=760, height=260):
    """series: [(label, class, {month: value})]; months: sorted 'YYYY-MM'. Direct labels at the right end."""
    vals = [v for _, _, d in series for v in d.values()]
    if not vals or len(months) < 1:
        return ""
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.1 or max(hi * 0.02, 1)
    lo, hi = max(lo - pad, 0), hi + pad
    left, right, top, bottom = 56, 140, 12, 26
    pw, ph = width - left - right, height - top - bottom
    xs = {m: left + (pw * i / max(len(months) - 1, 1)) for i, m in enumerate(months)}
    y = lambda v: top + ph - ph * (v - lo) / (hi - lo)
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="citations per month">']
    for i in range(0, 5):
        yy = top + ph - ph * i / 4
        out.append(f'<line class="grid" x1="{left}" y1="{yy:.1f}" x2="{left + pw}" y2="{yy:.1f}"/>'
                   f'<text class="axis" x="{left - 6}" y="{yy + 4:.1f}" text-anchor="end">{fmt(lo + (hi - lo) * i / 4)}</text>')
    for m in months:
        out.append(f'<text class="axis" x="{xs[m]:.1f}" y="{height - 8}" text-anchor="middle">{m}</text>')
    for label, cls, d in series:
        pts = [(xs[m], y(d[m]), m, d[m]) for m in months if m in d]
        if not pts:
            continue
        out.append(f'<polyline class="ln {cls}" points="{" ".join(f"{a:.1f},{b:.1f}" for a, b, _, _ in pts)}"/>')
        for a, b, m, v in pts:
            out.append(f'<circle class="dot {cls}" cx="{a:.1f}" cy="{b:.1f}" r="4"><title>{escape(label)} · {m}: {fmt(v)}</title></circle>')
        a, b, _, v = pts[-1]
        out.append(f'<text class="lbl" x="{a + 8:.1f}" y="{b + 4:.1f}">{escape(label)}</text>')
    out.append("</svg>")
    return "".join(out)


def spark(values, width=120, height=28):
    """values: [number]; a one-line trend with the last point marked."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pts = [(4 + (width - 8) * i / (len(values) - 1), 4 + (height - 8) * (1 - (v - lo) / span)) for i, v in enumerate(values)]
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" aria-hidden="true"><polyline class="ln s1" points="'
            + " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + f'"/><circle class="dot s1" cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3"/></svg>')
