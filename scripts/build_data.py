# -*- coding: utf-8 -*-
"""Build compact GeoJSON/JSON for the China passenger railway atlas.

Inputs (in data/raw):
  rp_web/data/network.json   OSM-derived rail graph (decoded delta coords)
  rp_web/data/stations.json  12306 stations with lon/lat
  rp_web/data/paths.json     train path segment geometry
  rp_web/data/trains.json    train stop sequences
  rp_web/data/basemap/*.json Natural- Earth / OSM basemap layers
  china_provinces.json       DataV province boundaries (including South China Sea islands)

Outputs (in data/out):
  rail.json, stations.json, line_index.json, meta.json, basemap.json
"""
import base64, collections, gzip, json, math, os, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "out"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "src"))
import line_meta

R = 6371008.8
RAD = math.pi / 180

def hav(lon1, lat1, lon2, lat2):
    dlat = (lat2 - lat1) * RAD
    dlon = (lon2 - lon1) * RAD
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * RAD) * math.cos(lat2 * RAD) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))

def decode_path(p):
    if p[0] == -1:
        return p
    out = [p[0], p[1], p[2]]
    prev = abs(p[2])
    for v in p[3:]:
        neg = v & 1
        z = v >> 1
        d = -((z + 1) // 2) if z & 1 else z // 2
        prev += d
        out.append(-prev if neg else prev)
    return out

def normalize_name(raw):
    if not raw:
        return ""
    raw = raw.strip()
    if raw in line_meta.ALIASES:
        return line_meta.ALIASES[raw]
    # strip bilingual suffix (keep the initial Chinese part)
    if " " in raw and re.search(r"[\u4e00-\u9fff]", raw):
        head = raw.split(" ")[0]
        if head in line_meta.ALIASES:
            return line_meta.ALIASES[head]
        if re.fullmatch(r"[\u4e00-\u9fff（）()·]+", head):
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
        raw = raw[:-2] + "际" if False else raw[:-2]
    elif raw.endswith("城际线"):
        raw = raw[:-3] + "城际"
    elif raw.endswith("铁路"):
        pass
    elif raw.endswith("线") and not raw.endswith("联络线"):
        raw = raw[:-1] + "铁路"
    return raw

def is_excluded(name):
    if not name:
        return True
    if re.search(r"[三四](线|铁路)$", name):
        return True
    if re.search(r"^[\dA-Za-z\s\.\-]+$", name):
        return True
    if any(p in name for p in line_meta.EXCLUDE_PATTERNS):
        return True
    if re.search(r"(上行|下行)(线|联络线|客车线)?$", name):
        return True
    if re.search(r"(动车|机车|车辆|客车)(段|所|场|线)$", name):
        return True
    if len(name) <= 1:
        return True
    return False

def rdp(points, eps):
    """Ramer-Douglas-Peucker, eps in degrees, equirectangular scaled by cos(lat)."""
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
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
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
    out = [p for p, k in zip(points, keep) if k]
    return out

def dist_point_seg_m(lon, lat, a, b):
    # local equirectangular approximation
    kx = math.cos(lat * RAD)
    ax, ay = a[0] * kx, a[1]
    bx, by = b[0] * kx, b[1]
    px, py = lon * kx, lat
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        t = 0.0
    else:
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy) * R * RAD

def load_json(name):
    with open(RAW / name, encoding="utf-8") as f:
        return json.load(f)

def poly_contains_ring(x, y, ring):
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-18) + xi):
            inside = not inside
        j = i
    return inside

def make_country_test(provinces):
    polys = []
    for f in provinces["features"]:
        g = f.get("geometry")
        if not g:
            continue
        if g["type"] == "Polygon":
            polys.append(g["coordinates"])
        elif g["type"] == "MultiPolygon":
            polys.extend(g["coordinates"])
    def inside(lon, lat):
        for poly in polys:
            if not poly:
                continue
            if poly_contains_ring(lon, lat, poly[0]):
                # holes
                if any(poly_contains_ring(lon, lat, hole) for hole in poly[1:]):
                    continue
                return True
        return False
    return inside

def point_in_any_province(lon, lat, provinces):
    for f in provinces["features"]:
        if f["properties"].get("name") == "":
            continue
        g = f.get("geometry")
        if not g:
            continue
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            if poly_contains_ring(lon, lat, poly[0]):
                if not any(poly_contains_ring(lon, lat, hole) for hole in poly[1:]):
                    return f["properties"].get("full") or f["properties"].get("name") or ""
    return ""

def line_speed_auto(name, cls, obs_p95):
    """Conservative class/observation based fallback, rounded to standard bands."""
    bands = [80, 120, 160, 200, 250, 300, 350]
    if cls == 0:
        floor, cap = 250, 350
    elif cls == 1:
        floor, cap = 160, 250
    else:
        floor, cap = 80, 160
    if obs_p95 is None:
        v = {0: 250, 1: 200, 2: 160, 3: 120}.get(cls, 120)
    else:
        # observed section average, intentionally converted to the nearest
        # *maximum* speed band using ~85% of the upper band.
        if obs_p95 >= 285: v = 350
        elif obs_p95 >= 250: v = 300
        elif obs_p95 >= 220: v = 250
        elif obs_p95 >= 175: v = 200
        elif obs_p95 >= 135: v = 160
        elif obs_p95 >= 95: v = 120
        else: v = 80
    v = max(floor, min(cap, v))
    return min(bands, key=lambda b: abs(b - v))

def line_type(name, speed):
    if name in line_meta.TYPE_OVERRIDES:
        return line_meta.TYPE_OVERRIDES[name]
    if "城际" in name:
        return "城际铁路"
    if speed >= 250:
        return "高速客运专线"
    if speed >= 200:
        return "快速铁路"
    return "客货共线铁路"

def band_name(speed):
    if speed >= 350: return "350"
    if speed >= 300: return "300"
    if speed >= 250: return "250"
    if speed >= 200: return "200"
    if speed >= 160: return "160"
    if speed >= 140: return "140"
    if speed >= 120: return "120"
    return "80"

def simplify_ring(ring, eps):
    # rings should preserve closure
    if len(ring) < 4:
        return ring
    closed = ring[0] == ring[-1]
    pts = ring[:-1] if closed else ring
    simp = rdp(pts, eps)
    if closed:
        if simp[0] != simp[-1]:
            simp = simp + [simp[0]]
    return simp

def main():
    t0 = time.time()
    print("loading inputs...")
    net = load_json("rp_web/data/network.json")
    st = load_json("rp_web/data/stations.json")
    provinces = load_json("china_provinces.json")
    names = net["names"]
    q = net["q"]
    inside_china = make_country_test(provinces)

    # Decode all edges to simple dicts
    print("decoding network...")
    edges = []
    for ei, row in enumerate(net["edges"]):
        n = (len(row) - 3) // 2
        lons = [0.0] * n; lats = [0.0] * n
        x = y = 0
        for k in range(n):
            x += row[3 + 2 * k]; y += row[4 + 2 * k]
            lons[k] = x / q; lats[k] = y / q
        # length
        L = 0.0
        for k in range(1, n):
            L += hav(lons[k - 1], lats[k - 1], lons[k], lats[k])
        edges.append({
            "i": ei, "cls": row[0], "raw": names[row[1]] if row[1] < len(names) else "",
            "name": "", "traffic": row[2], "lon": lons, "lat": lats, "len": L,
        })

    # Filter and normalize
    print("filtering passenger edges...")
    selected = []
    raw_to_name = {}
    for e in edges:
        if e["traffic"] <= 0 or e["cls"] in (4, 5, 6) or not e["raw"]:
            continue
        nm = normalize_name(e["raw"])
        if is_excluded(nm):
            continue
        if e["len"] < 80:
            continue
        # midpoint inside China (keeps Hainan / HK / border lines, drops foreign sections)
        mid = len(e["lon"]) // 2
        if not inside_china(e["lon"][mid], e["lat"][mid]):
            continue
        e["name"] = nm
        raw_to_name[e["raw"]] = nm
        selected.append(e)
    print("selected edges:", len(selected), "lines:", len(set(e["name"] for e in selected)))

    # Train paths are used both for observed speeds and for accurate station-line membership.
    print("decoding train paths...")
    tr = load_json("rp_web/data/trains.json")
    TF = {k: i for i, k in enumerate(tr["fields"])}
    paths = load_json("rp_web/data/paths.json")
    segs = [decode_path(p) for p in paths["segs"]]
    edge_line = {e["i"]: e["name"] for e in selected}
    path_line_cache = {}
    def path_lines_near(segidx, at_end):
        """Line names on the 1-2 track links immediately adjacent to a station.

        Using the whole stop-to-stop path over-associates long parallel corridors
        with both ends; the platform throat only tells us what the station serves.
        """
        key = (segidx, at_end)
        if key in path_line_cache:
            return path_line_cache[key]
        p = segs[segidx]
        names = set()
        if p[0] != -1:
            es = [abs(se) - 1 for se in p[3:]]
            near = es[-2:] if at_end else es[:2]
            for e in near:
                nm = edge_line.get(e)
                if nm:
                    names.add(nm)
        names = frozenset(names)
        path_line_cache[key] = names
        return names

    # Lines adjacent to each station in the booked timetable paths.
    print("mapping station-line services...")
    SF0 = {k: i for i, k in enumerate(st["fields"])}
    raw_station_name = [r[SF0["name"]] for r in st["rows"]]
    allowed_by_station = collections.defaultdict(set)
    for row in tr["rows"]:
        stops = row[TF["stops"]]
        ns = len(stops) // 5
        for k in range(ns):
            si = stops[5 * k]
            if si < 0 or si >= len(raw_station_name):
                continue
            nm = raw_station_name[si]
            if k > 0:
                prevseg = abs(stops[5 * (k - 1) + 4]) - 1
                if 0 <= prevseg < len(segs):
                    allowed_by_station[nm].update(path_lines_near(prevseg, True))
            outseg = abs(stops[5 * k + 4]) - 1
            if 0 <= outseg < len(segs):
                allowed_by_station[nm].update(path_lines_near(outseg, False))

    # Observed speed per line, cached for repeatability
    obs_cache = OUT / "line_obs.json"
    observed = {}
    if obs_cache.exists():
        observed = json.loads(obs_cache.read_text())
        print("loaded observed speed cache", len(observed))
    else:
        print("computing observed section speeds...")
        vals = collections.defaultdict(list)
        for row in tr["rows"]:
            stops = row[TF["stops"]]
            ns = len(stops) // 5
            for k in range(ns - 1):
                s0 = stops[5 * k:5 * k + 5]
                s1 = stops[5 * k + 5:5 * k + 10]
                segidx = abs(s0[4]) - 1
                if segidx < 0 or segidx >= len(segs):
                    continue
                dur = s1[1] - s0[2]
                dist = (s1[3] - s0[3]) * 10.0
                if dur <= 0 or dist < 30000:
                    continue
                avg = dist / dur * 60.0 / 1000.0
                if avg < 40 or avg > 400:
                    continue
                p = segs[segidx]
                if p[0] == -1:
                    continue
                lnames = set()
                for se in p[3:]:
                    nm = edge_line.get(abs(se) - 1)
                    if nm:
                        lnames.add(nm)
                for nm in lnames:
                    vals[nm].append(avg)
        for nm, arr in vals.items():
            arr.sort()
            if len(arr) >= 3:
                p95 = arr[min(len(arr) - 1, int(len(arr) * 0.95))]
                observed[nm] = round(p95, 1)
        obs_cache.write_text(json.dumps(observed, ensure_ascii=False), encoding="utf-8")
        print("observed lines:", len(observed))

    # Group selected edges by normalized name
    groups = collections.defaultdict(list)
    for e in selected:
        groups[e["name"]].append(e)

    # Line metadata
    line_objs = []
    for nm, es in groups.items():
        total_len = sum(e["len"] for e in es)
        traffic = max(e["traffic"] for e in es)
        classes = set(e["cls"] for e in es)
        speed = line_meta.SPEEDS.get(nm)
        if speed is None:
            speed = line_speed_auto(nm, min(classes), observed.get(nm))
        # curated values can be below the auto floor for a class but keep them
        speed = int(speed)
        line_objs.append({
            "name": nm, "speed": speed, "band": band_name(speed),
            "traffic": traffic, "edges": len(es), "length": total_len,
            "classes": sorted(classes), "type": line_type(nm, speed),
            "note": line_meta.NOTES.get(nm, ""),
        })
    # Initial stable IDs; final display tiers are computed after station association.
    line_objs.sort(key=lambda x: (-x["traffic"], x["name"]))
    for idx, L in enumerate(line_objs):
        L["id"] = idx
        L["tier"] = 4
        L["speedText"] = f"{L['speed']}"
        L["label"] = f"{L['name']}  {L['speed']}"
        L["selected"] = False
    name_to_line = {L["name"]: L for L in line_objs}
    print("lines:", len(line_objs))

    # Connected components per line using endpoint grid
    print("building geometry components...")
    def endkey(lon, lat):
        return (round(lon, 4), round(lat, 4))
    features = []
    feature_id = 0
    for L in line_objs:
        es = groups[L["name"]]
        parent = list(range(len(es)))
        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
        endpoint_map = {}
        for i, e in enumerate(es):
            for key in (endkey(e["lon"][0], e["lat"][0]), endkey(e["lon"][-1], e["lat"][-1])):
                if key in endpoint_map:
                    union(i, endpoint_map[key])
                else:
                    endpoint_map[key] = i
        comps = collections.defaultdict(list)
        for i, e in enumerate(es):
            comps[find(i)].append(es[i])
        for comp_edges in comps.values():
            # choose simplification tolerance by class
            eps = 0.0022 if min(L["classes"]) >= 2 else 0.0012
            lines = []
            for e in comp_edges:
                pts = list(zip(e["lon"], e["lat"]))
                if len(pts) > 2:
                    simp = rdp(pts, eps)
                else:
                    simp = pts
                # round and de-duplicate
                clean = []
                for p in simp:
                    cp = [round(p[0], 5), round(p[1], 5)]
                    if not clean or clean[-1] != cp:
                        clean.append(cp)
                if len(clean) >= 2:
                    lines.append(clean)
            if not lines:
                continue
            features.append({
                "type": "Feature", "id": feature_id,
                "properties": {
                    "k": L["id"], "n": L["name"], "s": L["speed"], "b": L["band"],
                    "t": L["traffic"], "z": L["tier"], "y": L["type"],
                },
                "geometry": {"type": "MultiLineString", "coordinates": lines},
            })
            feature_id += 1
    print("features:", len(features))

    # Spatial index of line segments for station association
    print("indexing line segments...")
    CELL = 0.05
    grid = collections.defaultdict(list)
    seg_meta = []
    for L in line_objs:
        for e in groups[L["name"]]:
            for k in range(1, len(e["lon"])):
                a = (e["lon"][k - 1], e["lat"][k - 1])
                b = (e["lon"][k], e["lat"][k])
                cx = int((a[0] + b[0]) / 2 / CELL)
                cy = int((a[1] + b[1]) / 2 / CELL)
                idx = len(seg_meta)
                seg_meta.append((L["id"], L["name"], a, b))
                # add to nearby cells to allow query at station cell
                grid[(cx, cy)].append(idx)
                # enough because station query uses 4x4 neighborhood around station

    # Station enrichment
    print("enriching stations...")
    SF = {k: i for i, k in enumerate(st["fields"])}
    stations = []
    station_line_map = collections.defaultdict(list)
    for r in st["rows"]:
        name = r[SF["name"]]
        lon = r[SF["x"]] / 1e5
        lat = r[SF["y"]] / 1e5
        city = r[SF["city"]] or ""
        tele = r[SF["tele"]] or ""
        py = r[SF["py"]] or ""
        abbr = r[SF["abbr"]] or ""
        rank = r[SF["rank"]] or 0
        if not (73 <= lon <= 136 and 17 <= lat <= 54.5):
            continue
        # candidate segments in 4x4 cells (±0.1° ≈ 11km), keep nearest per line
        cx = int(lon / CELL); cy = int(lat / CELL)
        cand = []
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                cand.extend(grid.get((cx + dx, cy + dy), ()))
        best = {}
        for idx in cand:
            lid, nm, a, b = seg_meta[idx]
            d = dist_point_seg_m(lon, lat, a, b)
            if d < best.get(lid, (1e9, None))[0]:
                best[lid] = (d, nm)
        # Only keep lines that both pass near the station and are actually traversed
        # by a booked train serving that station. This avoids assigning parallel lines.
        allowed = allowed_by_station.get(name)
        assoc = []
        for lid, (d, nm) in best.items():
            if d <= 2600 and allowed is not None and nm in allowed:
                assoc.append((d, lid, nm))
        if not assoc:
            # fall back to the nearest two physical lines for halts without parsed paths
            near = sorted((d, lid, nm) for lid, (d, nm) in best.items() if d <= 1800)[:2]
            assoc = near
        assoc.sort()
        # avoid an implausible cluster of lines at a tiny halt: keep at most 7, closest first
        assoc = assoc[:7]
        province = point_in_any_province(lon, lat, provinces)
        lines_info = [{"name": nm, "d": round(d), "speed": name_to_line[nm]["speed"]} for d, lid, nm in assoc]
        # sorted by speed and proximity for display
        lines_info.sort(key=lambda x: (-x["speed"], x["d"]))
        st_obj = {
            "name": name, "city": city, "province": province, "lon": round(lon, 5), "lat": round(lat, 5),
            "tele": tele, "py": py, "abbr": abbr, "rank": rank, "lines": lines_info,
        }
        stations.append(st_obj)
        for li in lines_info:
            station_line_map[li["name"]].append((st_obj, li["d"]))

    # Attach line stats / station lists
    for L in line_objs:
        sl = station_line_map.get(L["name"], [])
        # unique by station name
        seen = set(); unique = []
        for s, d in sorted(sl, key=lambda x: (-x[0]["rank"], x[1])):
            if s["name"] in seen:
                continue
            seen.add(s["name"]); unique.append((s, d))
        L["stationCount"] = len(unique)
        L["stations"] = [dict(s, distance=d) for s, d in unique[:10]]
        # record station membership on station object as well
        # (already populated above)
    # Drop spurious short stationless fragments; keep long/known lines even with sparse stops
    keep_names = set()
    for L in line_objs:
        if L["stationCount"] >= 1:
            keep_names.add(L["name"])
        elif L["length"] > 80000 and L["speed"] >= 120:
            keep_names.add(L["name"])
    # If station association missed everything, retain a handful of nationally important lines.
    for nm in ("青藏铁路", "川藏铁路", "中老铁路", "成昆铁路", "宝成铁路"):
        if nm in groups:
            keep_names.add(nm)
    line_objs = [L for L in line_objs if L["name"] in keep_names]
    groups = {k: v for k, v in groups.items() if k in keep_names}
    features = [f for f in features if f["properties"]["n"] in keep_names]

    featured = {
        "青藏铁路": 260, "川藏铁路": 250, "中老铁路": 220, "海南东环高铁": 170,
        "京张高铁": 190, "福厦高铁": 150, "广深港高铁": 130, "京津城际": 95,
        "沪宁城际": 70, "兰新高铁": 90, "成昆铁路": 110, "宝成铁路": 90,
        "滨绥铁路": 70, "滨洲铁路": 70, "包兰铁路": 60, "焦柳铁路": 65,
        "宁西铁路": 55, "襄渝铁路": 55, "京包铁路": 55, "沈大铁路": 50,
        "胶济铁路": 40, "沪蓉铁路": 55, "京九铁路": 40, "京哈铁路": 30,
    }
    for L in line_objs:
        L["score"] = (L["stationCount"] * 2.8 + min(L["edges"], 600) * 1.0
                      + L["traffic"] * 0.45 + (70 if L["speed"] >= 250 else 0))
        if L["speed"] <= 160 and L["edges"] > 300:
            L["score"] += 80
        if "城际" in L["name"] and L["name"] not in ("沪宁城际", "京津城际", "长珲城际", "广珠城际"):
            L["score"] -= 110
        if L["stationCount"] < 3:
            L["score"] -= 150
        if L["stationCount"] < 2:
            L["score"] -= 250
        L["score"] += featured.get(L["name"], 0)
    line_objs.sort(key=lambda x: (-x["score"], x["name"]))
    for new_id, L in enumerate(line_objs):
        L["id"] = new_id
        L["tier"] = 1 if new_id < 30 else 2 if new_id < 130 else 3 if new_id < 320 else 4
    name_to_line = {L["name"]: L for L in line_objs}

    # Clean station -> line references and recompute line station lists
    for stn in stations:
        stn["lines"] = [x for x in stn["lines"] if x["name"] in keep_names][:7]
    for L in line_objs:
        entries = []
        for stn in stations:
            for li in stn["lines"]:
                if li["name"] == L["name"]:
                    entries.append((stn, li["d"]))
                    break
        entries.sort(key=lambda x: (-x[0]["rank"], x[1]))
        seen = set(); uniq = []
        for stn, d in entries:
            if stn["name"] in seen:
                continue
            seen.add(stn["name"]); uniq.append((stn, d))
        L["stationCount"] = len(uniq)
        L["stations"] = [dict(stn, distance=d) for stn, d in uniq[:10]]
        L["cities"] = len(set(stn["city"] for stn, _ in uniq if stn.get("city")))

    # Rewrite feature properties against the final line table, and re-id features.
    for fid, f in enumerate(features):
        f["id"] = fid
        L = name_to_line[f["properties"]["n"]]
        f["properties"] = {
            "k": L["id"], "n": L["name"], "s": L["speed"], "b": L["band"],
            "t": L["traffic"], "z": L["tier"], "y": L["type"],
        }

    stations.sort(key=lambda s: (-s["rank"], s["name"]))
    for idx, s in enumerate(stations):
        s["id"] = idx
        s["tier"] = 1 if idx < 40 else 2 if idx < 220 else 3 if idx < 900 else 4
        s["lines"] = s["lines"][:7]

    # Line detail station snapshots were created before station IDs existed;
    # re-link them so station chips in the UI can open the correct station.
    station_by_name = {s["name"]: s for s in stations}
    for L in line_objs:
        linked = []
        for old in L.get("stations", []):
            stn = station_by_name.get(old["name"])
            if stn:
                linked.append({**stn, "distance": old.get("distance", 0)})
        L["stations"] = linked

    # Basemap: round & compress
    print("preparing basemap...")
    def load_base(name):
        return load_json("rp_web/data/basemap/" + name)
    def round_coords(obj, nd=4):
        if isinstance(obj, (int, float)):
            return round(obj, nd)
        if isinstance(obj, list):
            return [round_coords(v, nd) for v in obj]
        if isinstance(obj, dict):
            return {k: round_coords(v, nd) for k, v in obj.items()}
        return obj
    base = {
        "land": load_base("land.json"),
        "provinces": load_base("provinces.json"),
        "provLines": load_base("province-lines.json"),
        "nation": load_base("nation-line.json"),
        "dash": load_base("dashline.json"),
        "rivers": load_base("rivers.json"),
        "lakes": load_base("lakes.json"),
        "cities": load_base("cities.json"),
        "provLabels": load_base("province-labels.json"),
    }
    base = round_coords(base, 4)

    # Line-label anchors. A point symbol with an explicit rotation is more robust
    # than line-placement across the heavily fragmented OSM topology, while still
    # letting labels follow each corridor's local direction.
    print("building line label anchors...")
    features_by_line = collections.defaultdict(list)
    for f in features:
        features_by_line[f["properties"]["k"]].append(f)
    def seg_len(a, b):
        return hav(a[0], a[1], b[0], b[1])
    def bearing_deg(a, b):
        dx = (b[0] - a[0]) * math.cos((a[1] + b[1]) * .5 * RAD)
        dy = b[1] - a[1]
        return (math.degrees(math.atan2(dx, dy)) + 360) % 360
    label_feats = []
    for L in line_objs:
        # One anchor per visible OSM component, at local thirds/midpoint.
        # Multiple anchors let the renderer keep a line label near the viewport
        # when the user zooms into a long corridor.
        for comp_index, f in enumerate(features_by_line.get(L["id"], [])):
            all_lines = f["geometry"]["coordinates"]
            if not all_lines:
                continue
            def plen(line):
                return sum(seg_len(line[i - 1], line[i]) for i in range(1, len(line)))
            longest = max(all_lines, key=plen)
            total = plen(longest)
            if total < 700 or len(longest) < 2:
                continue
            cum = [0.0]
            for i in range(1, len(longest)):
                cum.append(cum[-1] + seg_len(longest[i - 1], longest[i]))
            fracs = [.33, .67] if total > 80000 else [.5]
            for ai, frac in enumerate(fracs):
                target = total * frac
                k = 1
                while k < len(cum) - 1 and cum[k] < target:
                    k += 1
                a = longest[k - 1]; b = longest[k]
                seg = max(1e-9, cum[k] - cum[k - 1])
                t = max(0.0, min(1.0, (target - cum[k - 1]) / seg))
                lon = a[0] + (b[0] - a[0]) * t
                lat = a[1] + (b[1] - a[1]) * t
                br = bearing_deg(a, b)
                rot = br - 90.0
                if rot > 90: rot -= 180
                if rot < -90: rot += 180
                if abs(rot) > 42: rot = 0.0
                label_feats.append({
                    "type": "Feature",
                    "properties": {
                        "k": L["id"], "n": L["name"], "s": L["speed"], "b": L["band"],
                        "t": L["traffic"], "z": L["tier"], "r": round(rot, 1),
                        "i": ai, "c": comp_index,
                    },
                    "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                })
    # Ensure every line has at least one label anchor (some very short fragments).
    labeled = set(f["properties"]["k"] for f in label_feats)
    for L in line_objs:
        if L["id"] in labeled:
            continue
        fl = features_by_line.get(L["id"], [])
        if not fl:
            continue
        line0 = fl[0]["geometry"]["coordinates"][0]
        if not line0:
            continue
        mid = line0[len(line0) // 2]
        label_feats.append({
            "type": "Feature",
            "properties": {"k": L["id"], "n": L["name"], "s": L["speed"], "b": L["band"],
                           "t": L["traffic"], "z": L["tier"], "r": 0, "i": 0},
            "geometry": {"type": "Point", "coordinates": [round(mid[0], 5), round(mid[1], 5)]},
        })
    print("label anchors:", len(label_feats))

    # Stats
    bands = collections.Counter(band_name(L["speed"]) for L in line_objs)
    meta = {
        "generated": time.strftime("%Y-%m-%d"),
        "snapshot": "2026-10-18",
        "osmSnapshot": "2026-09-24",
        "lines": len(line_objs),
        "stations": len(stations),
        "features": len(features),
        "cities": len(set(s["city"] for s in stations if s["city"])),
        "provinces": len(set(s["province"] for s in stations if s["province"])),
        "bands": dict(bands),
        "maxTraffic": max(L["traffic"] for L in line_objs),
    }

    # Write compact JSON
    print("writing...")
    def dump(obj, name):
        p = OUT / name
        p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(name, round(p.stat().st_size / 1024), "KB")
    dump({"type": "FeatureCollection", "features": features}, "rail.json")
    dump({"type": "FeatureCollection", "features": label_feats}, "line_labels.json")
    dump(stations, "stations.json")
    dump({"meta": meta, "lines": line_objs}, "line_index.json")
    dump(base, "basemap.json")
    dump(meta, "meta.json")
    print("done in", round(time.time() - t0, 1), "s")

if __name__ == "__main__":
    main()
