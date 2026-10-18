# -*- coding: utf-8 -*-
"""Fetch actual water-surface polygons for China's wide rivers/deltas.

OpenStreetMap's z10-z11 water layer contains river polygons (not just
centrelines) for the broad lower courses, deltas and estuaries.  Natural
Earth only provides a centreline for most of these rivers, which is why the
Yellow River and Qiantang estuary looked like single thin strokes.
"""
import json, math, sys, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.pydeps'))
import mapbox_vector_tile
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union

OUT = ROOT / 'data' / 'out'
CACHE = ROOT / 'data' / 'raw' / 'ofm_major'
CACHE.mkdir(parents=True, exist_ok=True)
TILE_VERSION = '20261011_080001_pt'
# name, west, south, east, north, zoom, include_ocean
REGIONS = [
    ('qiantang', 119.4, 29.6, 122.1, 31.1, 11, True),
    ('yangtze_mouth', 121.3, 30.8, 122.4, 32.2, 11, True),
    ('yellow_lower', 114.5, 34.5, 120.0, 38.5, 11, False),
    ('pearl', 111.5, 21.0, 115.2, 23.5, 10, True),
    ('huai', 115.5, 31.5, 121.0, 34.5, 10, False),
    ('liao', 120.5, 40.0, 123.5, 41.8, 10, True),
    ('hai', 116.5, 38.5, 118.5, 40.0, 10, True),
    ('min', 118.0, 25.5, 120.5, 26.8, 10, True),
    ('songhua', 124.0, 44.0, 132.0, 48.5, 9, False),
    ('amur', 125.0, 47.0, 135.0, 53.0, 9, False),
]

def tile_xy(lon, lat, z):
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)

def convert(coords, tx, ty, z):
    ext = 4096.0
    n = 2 ** z
    out = []
    def walk(c):
        if isinstance(c[0], (int, float)):
            x, y = c
            lon = (tx + x / ext) / n * 360.0 - 180.0
            yy = 1.0 - y / ext
            lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (ty + yy) / n))))
            out.append([lon, lat])
        else:
            for q in c: walk(q)
    walk(coords)
    return out

def main():
    features = []
    for name, w, s, e, n, z, ocean in REGIONS:
        x0, y0 = tile_xy(w, n, z)
        x1, y1 = tile_xy(e, s, z)
        print(name, 'z', z, 'tiles', (x1 - x0 + 1) * (y1 - y0 + 1), flush=True)
        geoms = []
        clip = box(w, s, e, n)
        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                p = CACHE / f'{z}_{tx}_{ty}.pbf'
                if not p.exists() or p.stat().st_size == 0:
                    url = f'https://tiles.openfreemap.org/planet/{TILE_VERSION}/{z}/{tx}/{ty}.pbf'
                    try:
                        req = urllib.request.Request(url, headers={'User-Agent': 'rail-atlas-research/1.0'})
                        with urllib.request.urlopen(req, timeout=30) as r: b = r.read()
                        p.write_bytes(b)
                    except Exception as ex:
                        print('tile fail', tx, ty, ex, flush=True)
                        continue
                try:
                    d = mapbox_vector_tile.decode(p.read_bytes())
                except Exception:
                    continue
                for f in d.get('water', {}).get('features', []):
                    cls = f.get('properties', {}).get('class')
                    if cls != 'river' and not (ocean and cls == 'ocean'):
                        continue
                    g = f.get('geometry', {})
                    typ = g.get('type'); c = g.get('coordinates')
                    if typ not in ('Polygon', 'MultiPolygon'):
                        continue
                    try:
                        if typ == 'Polygon':
                            obj = {'type': 'Polygon', 'coordinates': [convert(r, tx, ty, z) for r in c]}
                        else:
                            obj = {'type': 'MultiPolygon', 'coordinates': [[convert(r, tx, ty, z) for r in pc] for pc in c]}
                        geom = shape(obj)
                        if geom.is_valid and not geom.is_empty:
                            geoms.append(geom)
                    except Exception:
                        continue
        if not geoms:
            continue
        u = unary_union(geoms).intersection(clip)
        if u.is_empty:
            continue
        u = u.simplify(0.0003, preserve_topology=True)
        features.append({'type': 'Feature', 'properties': {'n': name, 'src': 'OSM/OpenFreeMap water', 'z': z},
                         'geometry': mapping(u)})
        print('  polygons', len(geoms), 'size', len(json.dumps(mapping(u))), 'bounds', u.bounds, flush=True)
    fc = {'type': 'FeatureCollection', 'features': features}
    p = OUT / 'major_water_areas.json'
    p.write_text(json.dumps(fc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('wrote', p, round(p.stat().st_size / 1024 / 1024, 2), 'MB', 'regions', len(features))

if __name__ == '__main__':
    main()
