# -*- coding: utf-8 -*-
"""Post-process rail data: add missing passenger services and complete station lists.

Adds:
  * 三乐旅游铁路 (Sanya–Yazhou tourist service, opened 2024-11-16; 200 km/h)
  * 金温铁路老线 (the old Jinhua–Wenzhou line, still carries a few K trains; 80 km/h)
and replaces the "top 10 by rank" station snapshots with every 12306 passenger
station on each line, ordered by the best available train stop sequence.
"""
import collections, json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'out'
RAW = ROOT / 'data' / 'raw' / 'rp_web' / 'data'
R = 6371008.8
RAD = math.pi / 180

def hav(a, b):
    dlat = (b[1] - a[1]) * RAD
    dlon = (b[0] - a[0]) * RAD
    x = math.sin(dlat / 2) ** 2 + math.cos(a[1] * RAD) * math.cos(b[1] * RAD) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(x)))

def decode_path(p):
    out = [p[0], p[1], p[2]]
    prev = abs(p[2])
    for v in p[3:]:
        neg = v & 1
        z = v >> 1
        d = -((z + 1) // 2) if z & 1 else z // 2
        prev += d
        out.append(-prev if neg else prev)
    return out

def main():
    lines_doc = json.loads((OUT / 'line_index.json').read_text(encoding='utf-8'))
    lines = lines_doc['lines']
    rail = json.loads((OUT / 'rail.json').read_text(encoding='utf-8'))
    labels = json.loads((OUT / 'line_labels.json').read_text(encoding='utf-8'))
    stations = json.loads((OUT / 'stations.json').read_text(encoding='utf-8'))
    meta = json.loads((OUT / 'meta.json').read_text(encoding='utf-8'))

    T = json.loads((RAW / 'trains.json').read_text(encoding='utf-8'))
    P = json.loads((RAW / 'paths.json').read_text(encoding='utf-8'))
    D = json.loads((RAW / 'network.json').read_text(encoding='utf-8'))
    RAWST = json.loads((RAW / 'stations.json').read_text(encoding='utf-8'))
    TF = {k: i for i, k in enumerate(T['fields'])}
    RF = {k: i for i, k in enumerate(RAWST['fields'])}
    raw_names = [r[RF['name']] for r in RAWST['rows']]
    q = D['q']
    by_name = {s['name']: s for s in stations}
    line_by_name = {L['name']: L for L in lines}
    max_id = max(L['id'] for L in lines)
    max_feature_id = max((f.get('id', -1) for f in rail['features']), default=-1) + 1

    def edge_coords(eid):
        row = D['edges'][eid]
        n = (len(row) - 3) // 2
        x = y = 0
        out = []
        for k in range(n):
            x += row[3 + 2 * k]
            y += row[4 + 2 * k]
            out.append([x / q, y / q])
        return out

    def edges_in_path(segidx):
        p = P['segs'][segidx]
        return [abs(v) - 1 for v in decode_path(p)[3:]]

    # ---- gather the exact edge set used by a six-stop Sanyue train -------------
    sanyue = None
    for row in T['rows']:
        stops = row[TF['stops']]
        seq = [raw_names[stops[5 * k]] for k in range(len(stops) // 5)]
        if seq == ['三亚', '凤凰机场', '天涯海角', '南山北', '崖州湾', '崖州']:
            sanyue = stops
            break
    if not sanyue:
        raise SystemExit('Sanyue train not found')
    sanyue_edges = []
    seen_edges = set()
    for k in range(len(sanyue) // 5):
        se = sanyue[5 * k + 4]
        if not se:
            continue
        for e in edges_in_path(abs(se) - 1):
            if e not in seen_edges:
                seen_edges.add(e)
                sanyue_edges.append(e)
    # route length uses unique edges; add short connectors from the station nodes
    sanyue_lines = []
    for e in sanyue_edges:
        c = edge_coords(e)
        if len(c) >= 2:
            sanyue_lines.append([[round(x, 6), round(y, 6)] for x, y in c])

    def nearest_endpoint(lines_, pt):
        best = None
        for line in lines_:
            for p in (line[0], line[-1]):
                d = hav(p, pt)
                if best is None or d < best[0]:
                    best = (d, p)
        return best

    def add_connector(lines_, a, b):
        if not lines_:
            return
        pta, ptb = [a['lon'], a['lat']], [b['lon'], b['lat']]
        da = nearest_endpoint(lines_, pta)
        db = nearest_endpoint(lines_, ptb)
        # only draw a short connector when the station approach is missing
        if da and da[0] > 250:
            lines_.append([[round(pta[0], 6), round(pta[1], 6)], da[1]])
        if db and db[0] > 250:
            lines_.append([db[1], [round(ptb[0], 6), round(ptb[1], 6)]])

    add_connector(sanyue_lines, by_name['三亚'], by_name['崖州'])
    sanyue_length = sum(hav(l[i - 1], l[i]) for l in sanyue_lines for i in range(1, len(l)))

    # ---- old Jinhua–Wenzhou line ----------------------------------------------
    jw_lines = []
    jw_length = 0.0
    for eid, row in enumerate(D['edges']):
        nm = D['names'][row[1]] if row[1] < len(D['names']) else ''
        if nm != '金温货线':
            continue
        c = edge_coords(eid)
        if len(c) >= 2:
            jw_lines.append([[round(x, 6), round(y, 6)] for x, y in c])
            jw_length += sum(hav(c[i - 1], c[i]) for i in range(1, len(c)))

    def longest_line(lines_):
        return max(lines_, key=lambda l: sum(hav(l[i - 1], l[i]) for i in range(1, len(l))))

    def label_anchor(L, lines_):
        if not lines_:
            return None
        line = longest_line(lines_)
        total = sum(hav(line[i - 1], line[i]) for i in range(1, len(line)))
        if total <= 0:
            return None
        cum = 0.0
        target = total * .5
        for i in range(1, len(line)):
            d = hav(line[i - 1], line[i])
            if cum + d >= target:
                a, b = line[i - 1], line[i]
                t = (target - cum) / max(d, 1e-9)
                lon = a[0] + (b[0] - a[0]) * t
                lat = a[1] + (b[1] - a[1]) * t
                dx = (b[0] - a[0]) * math.cos((a[1] + b[1]) * .5 * RAD)
                dy = b[1] - a[1]
                br = (math.degrees(math.atan2(dx, dy)) + 360) % 360
                rot = br - 90.0
                if rot > 90: rot -= 180
                if rot < -90: rot += 180
                if abs(rot) > 42: rot = 0.0
                return {
                    'type': 'Feature',
                    'properties': {'k': L['id'], 'n': L['name'], 's': L['speed'], 'b': L['band'],
                                   't': L['traffic'], 'z': L['tier'], 'r': round(rot, 1), 'i': 0, 'c': 0},
                    'geometry': {'type': 'Point', 'coordinates': [round(lon, 5), round(lat, 5)]},
                }
            cum += d
        return None

    def add_line(name, speed, typ, note, lines_, station_order, tier, traffic=20):
        nonlocal max_id, max_feature_id
        L = {
            'name': name, 'speed': speed, 'band': str(speed), 'traffic': traffic,
            'edges': len(lines_), 'length': round(sum(hav(l[i - 1], l[i]) for l in lines_ for i in range(1, len(l))), 1),
            'classes': [2], 'type': typ, 'note': note, 'id': max_id + 1, 'tier': tier,
            'speedText': str(speed), 'label': f'{name}  {speed}', 'selected': False,
            'stationCount': len(station_order), 'cities': 0,
            'stations': [],
        }
        max_id += 1
        lines.append(L)
        line_by_name[name] = L
        # member references on stations
        for nm in station_order:
            st = by_name.get(nm)
            if not st:
                continue
            if not any(x.get('name') == name for x in st['lines']):
                st['lines'].append({'name': name, 'd': 0, 'speed': speed})
        feat = {
            'type': 'Feature', 'id': max_feature_id,
            'properties': {'k': L['id'], 'n': name, 's': speed, 'b': str(speed),
                           't': traffic, 'z': tier, 'y': typ},
            'geometry': {'type': 'MultiLineString', 'coordinates': lines_},
        }
        max_feature_id += 1
        rail['features'].append(feat)
        anc = label_anchor(L, lines_)
        if anc:
            labels['features'].append(anc)
        return L

    sanyue_L = add_line(
        '三乐旅游铁路', 200, '旅游铁路',
        '利用海南西环高铁及既有西环铁路三亚—崖州段开行的公交化旅游列车，2024-11-16 开通，最高运营 200 km/h；现图定办客站为三亚、凤凰机场、天涯海角、南山北、崖州湾、崖州。',
        sanyue_lines, ['三亚', '凤凰机场', '天涯海角', '南山北', '崖州湾', '崖州'], 2, traffic=30)
    jw_L = add_line(
        '金温铁路老线', 80, '客货共线铁路',
        '即金温货线，既有金温铁路；仍办理少量普速旅客列车，按既有线 80 km/h 级标尺标注。',
        jw_lines, ['金华南', '武义', '永康南', '缙云', '丽水', '青田', '温州'], 3, traffic=25)

    # Put the new lines next to their relatives for a sensible directory order.
    def move_after(name, anchor_name):
        L = next((x for x in lines if x['name'] == name), None)
        if not L: return
        lines.remove(L)
        idx = next((i for i, x in enumerate(lines) if x['name'] == anchor_name), len(lines) - 1)
        lines.insert(idx + 1, L)
    move_after('三乐旅游铁路', '海南西环高铁')
    move_after('金温铁路老线', '金温铁路')

    # ---- clean parallel-line misassociations -----------------------------------
    # A station with one platform can be near several parallel corridors (e.g.
    # Anting North is 0 m from the Huning intercity and 21 m from the Beijing-
    # Shanghai HSR).  Keep an association only if no other line is decisively
    # closer.  Shared hubs with comparable distances are retained.
    for st in stations:
        entries = st.get('lines', [])
        kept = []
        for li in entries:
            d = li.get('d', 99999)
            if d > 2000:
                continue
            # Major hubs genuinely serve several parallel corridors; never
            # strip their associations just because another track is a few
            # metres closer.  Small local halts need the stricter test.
            if st.get('rank', 0) >= 100:
                kept.append(li)
                continue
            rivals = [x.get('d', 99999) for x in entries
                      if x is not li and x.get('d', 99999) < d - 10 and x.get('d', 99999) < max(60, d * 0.6)]
            if not rivals:
                kept.append(li)
        st['lines'] = kept

    # ---- full station lists, ordered -------------------------------------------
    line_stations = collections.defaultdict(dict)
    for s in stations:
        if s.get('rank', 0) <= 0:
            continue
        for li in s.get('lines', []):
            nm = li.get('name')
            if nm in line_by_name:
                line_stations[nm][s['name']] = s

    # Collect train stop sequences per line.  They are the strongest evidence
    # for along-route order, and naturally contain only 12306 passenger stops.
    line_seqs = collections.defaultdict(list)
    for row in T['rows']:
        stops = row[TF['stops']]
        seq = [raw_names[stops[5 * k]] for k in range(len(stops) // 5)]
        per = collections.defaultdict(list)
        seen = collections.defaultdict(set)
        for nm in seq:
            st = by_name.get(nm)
            if not st:
                continue
            for li in st.get('lines', []):
                ln = li.get('name')
                if ln not in line_stations or nm not in line_stations[ln]:
                    continue
                if nm not in seen[ln]:
                    per[ln].append(nm)
                    seen[ln].add(nm)
        for ln, sq in per.items():
            if len(sq) >= 2:
                line_seqs[ln].append(sq)

    def geom_along(L):
        feats = [f for f in rail['features'] if f['properties'].get('k') == L['id']]
        if not feats:
            return {}
        best_line = None
        best_len = -1
        for f in feats:
            for line in f['geometry']['coordinates']:
                ln = sum(hav(line[i - 1], line[i]) for i in range(1, len(line)))
                if ln > best_len:
                    best_len, best_line = ln, line
        if not best_line:
            return {}
        cum = [0.0]
        for i in range(1, len(best_line)):
            cum.append(cum[-1] + hav(best_line[i - 1], best_line[i]))
        out = {}
        for s in line_stations.get(L['name'], {}).values():
            pt = [s['lon'], s['lat']]
            best = None
            for i in range(1, len(best_line)):
                a, b = best_line[i - 1], best_line[i]
                kx = math.cos(pt[1] * RAD)
                ax, ay = a[0] * kx, a[1]
                bx, by = b[0] * kx, b[1]
                px, py = pt[0] * kx, pt[1]
                dx, dy = bx - ax, by - ay
                t = 0.0 if dx == 0 and dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
                q = (ax + t * dx, ay + t * dy)
                d = math.hypot(px - q[0], py - q[1])
                if best is None or d < best[0]:
                    best = (d, cum[i - 1] + t * (cum[i] - cum[i - 1]))
            out[s['name']] = best[1] if best else 0.0
        return out

    def pca_order(sts):
        if len(sts) < 2:
            return sts[:]
        lat0 = sum(s['lat'] for s in sts) / len(sts)
        kx = math.cos(math.radians(lat0))
        pts = [(s['lon'] * kx, s['lat']) for s in sts]
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        cxx = sum((p[0] - mx) ** 2 for p in pts)
        cyy = sum((p[1] - my) ** 2 for p in pts)
        cxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
        if abs(cxy) > 1e-12:
            vx, vy = cxy, (cxx + cyy) / 2 + math.sqrt(max(0, ((cxx + cyy) / 2) ** 2 - (cxx * cyy - cxy * cxy))) - cxx
        elif cxx >= cyy:
            vx, vy = 1.0, 0.0
        else:
            vx, vy = 0.0, 1.0
        norm = math.hypot(vx, vy) or 1.0
        vx /= norm; vy /= norm
        arr = sorted(zip(sts, [((s['lon'] * kx - mx) * vx + (s['lat'] - my) * vy) for s in sts]), key=lambda z: z[1])
        return [s for s, _ in arr]

    def order_for(L, sts):
        seqs = [sq for sq in line_seqs.get(L['name'], []) if len(sq) >= 2]
        if not seqs:
            return pca_order(sts)
        backbone = max(seqs, key=len)
        # PCA is a robust geographic backbone for long, mostly linear lines.
        # Keep it only when it agrees with a real train's stop order; curved
        # or looping corridors (Hainan, etc.) use the actual train order.
        pca = pca_order(sts)
        pos = {s['name']: i for i, s in enumerate(pca)}
        common = [n for n in backbone if n in pos]
        inv = 0; pairs = 0
        vals = [pos[n] for n in common]
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                pairs += 1
                if vals[i] > vals[j]:
                    inv += 1
        concord = 1.0 - (inv / pairs if pairs else 0.0)
        if concord < .5:
            pca = list(reversed(pca))
            pos = {s['name']: i for i, s in enumerate(pca)}
            vals = [pos[n] for n in common]
            inv = 0; pairs = 0
            for i in range(len(vals)):
                for j in range(i + 1, len(vals)):
                    pairs += 1
                    if vals[i] > vals[j]:
                        inv += 1
            concord = 1.0 - (inv / pairs if pairs else 0.0)
        if concord >= .7:
            return pca
        # Real train order; append station not covered by that service.
        placed = set(backbone)
        out = [s for s in sts if s['name'] in placed]
        out.sort(key=lambda s: backbone.index(s['name']))
        rest = [s for s in sts if s['name'] not in placed]
        rest.sort(key=lambda s: -s.get('rank', 0))
        return out + rest

    def snapshot(s):
        return {'id': s['id'], 'name': s['name'], 'city': s.get('city', ''),
                'province': s.get('province', ''), 'lon': s['lon'], 'lat': s['lat'],
                'rank': s['rank']}

    for L in lines:
        sts = list(line_stations.get(L['name'], {}).values())
        if not sts:
            L['stationCount'] = 0
            L['stations'] = []
            L['cities'] = 0
            continue
        ordered = order_for(L, sts)
        L['stations'] = [snapshot(s) for s in ordered]
        L['stationCount'] = len(ordered)
        L['cities'] = len({s.get('city') for s in ordered if s.get('city')})

    # Specific unambiguous orders for the new services
    sanyue_L['stations'] = [snapshot(by_name[n]) for n in ['三亚', '凤凰机场', '天涯海角', '南山北', '崖州湾', '崖州']]
    sanyue_L['stationCount'] = 6
    sanyue_L['cities'] = 2
    jw_L['stations'] = [snapshot(by_name[n]) for n in ['金华南', '武义', '永康南', '缙云', '丽水', '青田', '温州']]
    jw_L['stationCount'] = 7
    jw_L['cities'] = 3
    # The Hainan ring is a loop with a pronounced curve; a single geographic
    # axis cannot order it, so use the known coastal sequence explicitly.
    hainan_orders = {
        '海南东环高铁': ['海口', '长流', '秀英', '城西', '海口东', '美兰', '文昌', '琼海', '博鳌', '和乐', '万宁', '神州', '陵水', '亚龙湾', '三亚'],
        '海南西环高铁': ['海口', '老城镇', '福山镇', '临高南', '银滩', '白马井', '海头', '棋子湾', '东方', '金月湾', '尖峰', '黄流', '乐东', '凤凰机场', '三亚'],
    }
    for nm, order in hainan_orders.items():
        L = line_by_name.get(nm)
        if not L: continue
        have = {s['name']: s for s in L['stations']}
        if all(x in have for x in order):
            L['stations'] = [have[x] for x in order]
            L['stationCount'] = len(order)

    # ---- metadata / outputs ----------------------------------------------------
    lines_doc['lines'] = lines
    lines_doc['meta']['snapshot'] = meta.get('snapshot', '2026-10-18')
    bands = collections.Counter(L['band'] for L in lines)
    meta['lines'] = len(lines)
    meta['features'] = len(rail['features'])
    meta['bands'] = dict(sorted(bands.items(), key=lambda kv: -int(kv[0])))
    meta['maxTraffic'] = max(L['traffic'] for L in lines)
    meta['stationYardHubs'] = 8
    (OUT / 'line_index.json').write_text(json.dumps(lines_doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    (OUT / 'rail.json').write_text(json.dumps(rail, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    (OUT / 'line_labels.json').write_text(json.dumps(labels, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    (OUT / 'stations.json').write_text(json.dumps(stations, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    (OUT / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('lines', len(lines), 'features', len(rail['features']), 'labels', len(labels['features']))
    print('三乐', len(sanyue_lines), 'segments', round(sanyue_length / 1000, 1), 'km')
    print('金温老线', len(jw_lines), 'segments', round(jw_length / 1000, 1), 'km')
    print('bands', meta['bands'])

if __name__ == '__main__':
    main()
