# -*- coding: utf-8 -*-
"""Repair display geometry and build station-junction links.

1. Rebuild each line's geometry from *all* OSM edges carrying that line name,
   including edges with zero booked-passenger traffic.  This closes the small
   gaps (e.g. 沪春铁路 near Shanghai South) that the passenger-only selection
   left behind.
2. Bridge very short residual gaps between components of the same line.
3. For every 12306 passenger station served by two or more lines, connect the
   nearest points of those lines to a common junction node.  These links are
   cartographic, not track-accurate; they make interchanges legible without
   drawing the full station yard.
"""
import json, math, sys, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'out'
RAW = ROOT / 'data' / 'raw' / 'rp_web' / 'data'
sys.path.insert(0, str(ROOT / 'src'))
import line_meta

R = 6371008.8
RAD = math.pi / 180
NEW_LINES = {'三乐旅游铁路', '金温铁路老线'}

def hav(a, b):
    dlat = (b[1] - a[1]) * RAD
    dlon = (b[0] - a[0]) * RAD
    x = math.sin(dlat / 2) ** 2 + math.cos(a[1] * RAD) * math.cos(b[1] * RAD) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(x)))

def normalize_name(raw):
    if not raw:
        return ""
    raw = raw.strip()
    if raw in line_meta.ALIASES:
        return line_meta.ALIASES[raw]
    if " " in raw:
        head = raw.split(" ")[0]
        if head in line_meta.ALIASES:
            return line_meta.ALIASES[head]
        if all('\u4e00' <= c <= '\u9fff' or c in '（）()·' for c in head):
            raw = head
    if raw.endswith("高速铁路"):
        raw = raw[:-4] + "高铁"
    elif raw.endswith("高速线"):
        raw = raw[:-3] + "高铁"
    elif raw.endswith("客运专线"):
        raw = raw[:-4] + "客专"
    elif raw.endswith("客专线"):
        raw = raw[:-3] + "客专"
    elif raw.endswith("城际铁路"):
        raw = raw[:-2]
    elif raw.endswith("城际线"):
        raw = raw[:-3] + "城际"
    elif raw.endswith("铁路"):
        pass
    elif raw.endswith("线") and not raw.endswith("联络线"):
        raw = raw[:-1] + "铁路"
    return raw

def rdp(points, eps):
    if len(points) < 3:
        return points
    lat0 = sum(p[1] for p in points) / len(points)
    kx = math.cos(lat0 * RAD)
    def dist2(p, a, b):
        ax, ay = a[0] * kx, a[1]
        bx, by = b[0] * kx, b[1]
        px, py = p[0] * kx, p[1]
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return (px - ax) ** 2 + (py - ay) ** 2
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        qx, qy = ax + t * dx, ay + t * dy
        return (px - qx) ** 2 + (py - qy) ** 2
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    eps2 = eps * eps
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        maxd = -1.0; idx = -1
        for k in range(i + 1, j):
            d = dist2(points[k], points[i], points[j])
            if d > maxd:
                maxd = d; idx = k
        if maxd > eps2:
            keep[idx] = True
            stack.append((i, idx)); stack.append((idx, j))
    return [p for p, k in zip(points, keep) if k]

def decode_edge(row, q):
    n = (len(row) - 3) // 2
    x = y = 0
    out = []
    for k in range(n):
        x += row[3 + 2 * k]
        y += row[4 + 2 * k]
        out.append((x / q, y / q))
    return out

def point_seg(p, a, b):
    kx = math.cos(p[1] * RAD)
    ax, ay = a[0] * kx, a[1]
    bx, by = b[0] * kx, b[1]
    px, py = p[0] * kx, p[1]
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    q = (ax + t * dx, ay + t * dy)
    return math.hypot(px - q[0], py - q[1]) * R * RAD, [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]

def main():
    lines_doc = json.loads((OUT / 'line_index.json').read_text(encoding='utf-8'))
    lines = lines_doc['lines']
    line_by_name = {L['name']: L for L in lines}
    rail = json.loads((OUT / 'rail.json').read_text(encoding='utf-8'))
    stations = json.loads((OUT / 'stations.json').read_text(encoding='utf-8'))
    D = json.loads((RAW / 'network.json').read_text(encoding='utf-8'))
    names = D['names']; q = D['q']

    # ---- collect all edges by normalized line name ----------------------------
    groups = collections.defaultdict(list)
    for ei, row in enumerate(D['edges']):
        cls = row[0]
        if cls >= 4 or row[1] >= len(names):
            continue
        raw = names[row[1]]
        if not raw:
            continue
        nm = normalize_name(raw)
        if nm not in line_by_name or nm in NEW_LINES:
            continue
        pts = decode_edge(row, q)
        if not pts:
            continue
        mid = pts[len(pts) // 2]
        if not (73 <= mid[0] <= 136 and 17 <= mid[1] <= 54.5):
            continue
        groups[nm].append((ei, pts))

    # Replace each eligible line with one MultiLineString made of all its edges.
    keep_feats = []
    for f in rail['features']:
        if f['properties'].get('n') in groups:
            continue
        keep_feats.append(f)
    rebuilt = []
    for nm, edges in groups.items():
        L = line_by_name[nm]
        lines_ = []
        for ei, pts in edges:
            eps = 0.00012 if D['edges'][ei][0] <= 1 else 0.00035
            simp = rdp(pts, eps) if len(pts) > 2 else pts
            clean = []
            for p in simp:
                c = [round(p[0], 6), round(p[1], 6)]
                if not clean or clean[-1] != c:
                    clean.append(c)
            if len(clean) >= 2:
                lines_.append(clean)
        if not lines_:
            continue
        # Bridge tiny residual gaps between components (<= 300 m).  The edges
        # are grouped by line name, so this only joins same-line fragments.
        def endpoints(ls):
            return { (round(ls[0][0], 5), round(ls[0][1], 5)), (round(ls[-1][0], 5), round(ls[-1][1], 5)) }
        for _ in range(8):
            # components by shared endpoint (snap 5 decimals)
            n = len(lines_)
            par = list(range(n))
            def find(a):
                while par[a] != a:
                    par[a] = par[par[a]]; a = par[a]
                return a
            def union(a, b):
                ra, rb = find(a), find(b)
                if ra != rb: par[rb] = ra
            buckets = collections.defaultdict(list)
            for i, ls in enumerate(lines_):
                for k in endpoints(ls):
                    buckets[k].append(i)
            for ids in buckets.values():
                for j in ids[1:]: union(ids[0], j)
            comps = collections.defaultdict(list)
            for i in range(n): comps[find(i)].append(i)
            if len(comps) <= 1:
                break
            roots = list(comps)
            best = None
            for ia in range(len(roots)):
                for ib in range(ia + 1, len(roots)):
                    for ai in comps[roots[ia]]:
                        for bi in comps[roots[ib]]:
                            for pa in (lines_[ai][0], lines_[ai][-1]):
                                for pb in (lines_[bi][0], lines_[bi][-1]):
                                    d = hav(pa, pb)
                                    if best is None or d < best[0]:
                                        best = (d, pa, pb)
            if not best or best[0] > 300:
                break
            _, pa, pb = best
            lines_.append([[round(pa[0], 6), round(pa[1], 6)], [round(pb[0], 6), round(pb[1], 6)]])
        rebuilt.append({
            'type': 'Feature', 'properties': {
                'k': L['id'], 'n': nm, 's': L['speed'], 'b': L['band'],
                't': L['traffic'], 'z': L['tier'], 'y': L['type'],
            },
            'geometry': {'type': 'MultiLineString', 'coordinates': lines_},
        })
    features = keep_feats + rebuilt
    for i, f in enumerate(features):
        f['id'] = i
    rail['features'] = features
    print('rebuilt lines', len(rebuilt), 'features', len(features))

    # ---- junction links ------------------------------------------------------
    geo_by_line = collections.defaultdict(list)
    for f in features:
        nm = f['properties'].get('n')
        for ls in f['geometry']['coordinates']:
            if len(ls) >= 2:
                geo_by_line[nm].append(ls)

    def nearest(nm, pt):
        best = None
        for ls in geo_by_line.get(nm, []):
            for i in range(1, len(ls)):
                d, qpt = point_seg(pt, ls[i - 1], ls[i])
                if best is None or d < best[0]:
                    best = (d, qpt)
        return best

    links = []
    nodes = []
    for st in stations:
        if st.get('rank', 0) <= 0:
            continue
        line_names = []
        for li in st.get('lines', []):
            nm = li.get('name')
            if nm in geo_by_line and nm not in line_names:
                line_names.append(nm)
        if len(line_names) < 2:
            continue
        pt = [st['lon'], st['lat']]
        found = []
        for nm in line_names:
            hit = nearest(nm, pt)
            if hit and hit[0] <= 1200:
                found.append((nm, hit[0], hit[1]))
        if len(found) < 2:
            continue
        # Hub node at the station point; do not invent a long track through a
        # station throat.  Only connect lines that genuinely pass within 180 m
        # of the station, and draw those links as a faint cartographic tie.
        clines = []
        for nm, d, qpt in found:
            if d <= 180:
                if hav(qpt, pt) > 12:
                    links.append({
                        'type': 'Feature', 'properties': {'n': st['name'], 'l': nm},
                        'geometry': {'type': 'LineString', 'coordinates': [[round(qpt[0], 6), round(qpt[1], 6)], [round(pt[0], 6), round(pt[1], 6)]]},
                    })
                clines.append(nm)
        if len(clines) < 2:
            # Keep the hub halo even when the station point is a little away
            # from the simplified track centreline.
            clines = [x[0] for x in found]
        nodes.append({
            'type': 'Feature', 'properties': {'n': st['name'], 'c': len(clines), 'l': '、'.join(clines)},
            'geometry': {'type': 'Point', 'coordinates': [round(pt[0], 6), round(pt[1], 6)]},
        })
    # de-duplicate identical connectors
    seen = set(); uniq = []
    for f in links:
        c = f['geometry']['coordinates']
        key = (f['properties']['n'], tuple(c[0]), tuple(c[-1]))
        rk = (f['properties']['n'], tuple(c[-1]), tuple(c[0]))
        if key in seen or rk in seen:
            continue
        seen.add(key); uniq.append(f)
    junctions = {'links': {'type': 'FeatureCollection', 'features': uniq},
                 'nodes': {'type': 'FeatureCollection', 'features': nodes}}
    (OUT / 'junctions.json').write_text(json.dumps(junctions, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    (OUT / 'rail.json').write_text(json.dumps(rail, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('junction stations', len(nodes), 'links', len(uniq))
    print('rail', round((OUT / 'rail.json').stat().st_size / 1024 / 1024, 2), 'MB')
    # show Hu-Chun diagnostics
    hc = [f for f in features if f['properties'].get('n') == '沪春铁路']
    if hc:
        n = sum(len(x) for x in hc[0]['geometry']['coordinates'])
        print('沪春铁路 components', len(hc[0]['geometry']['coordinates']), 'points', n)

if __name__ == '__main__':
    main()
