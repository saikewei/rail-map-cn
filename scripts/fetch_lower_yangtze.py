# -*- coding: utf-8 -*-
"""Fetch lower-Yangtze river water polygons from OpenStreetMap vector tiles.

Natural Earth's 1:10m river centerline stops near 119.6E, so the wide
Yangtze estuary was missing.  OpenFreeMap's z10 water layer provides the
actual river surface polygons for the lower Yangtze.  We keep only water
class=river, merge tile-clipped pieces, and store a small GeoJSON.
"""
import json, math, sys, urllib.request, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.pydeps'))
import mapbox_vector_tile
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union

OUT = ROOT / 'data' / 'out'
CACHE = ROOT / 'data' / 'raw' / 'ofm_water'
CACHE.mkdir(parents=True, exist_ok=True)
Z = 11
BBOX = (119.4, 30.9, 122.3, 32.3)
TILE_VERSION = '20261011_080001_pt'

def tile_xy(lon, lat, z=Z):
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)

def convert(coords, tx, ty):
    """MVT local coordinates -> lon/lat (decoder default is y-up)."""
    ext = 4096.0
    n = 2 ** Z
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
    x0, y0 = tile_xy(BBOX[0], BBOX[3])
    x1, y1 = tile_xy(BBOX[2], BBOX[1])
    print('tiles', x0, x1, y0, y1, 'count', (x1-x0+1)*(y1-y0+1))
    geoms = []
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            p = CACHE / f'{Z}_{tx}_{ty}.pbf'
            if not p.exists() or p.stat().st_size == 0:
                url = f'https://tiles.openfreemap.org/planet/{TILE_VERSION}/{Z}/{tx}/{ty}.pbf'
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'rail-atlas-research/1.0'})
                    with urllib.request.urlopen(req, timeout=30) as r: b = r.read()
                    p.write_bytes(b)
                except Exception as e:
                    print('tile fail', tx, ty, e)
                    continue
            try:
                d = mapbox_vector_tile.decode(p.read_bytes())
            except Exception:
                continue
            for f in d.get('water', {}).get('features', []):
                if f.get('properties', {}).get('class') != 'river':
                    continue
                g = f.get('geometry', {})
                typ = g.get('type'); c = g.get('coordinates')
                if typ not in ('Polygon', 'MultiPolygon'):
                    continue
                try:
                    if typ == 'Polygon':
                        poly = {'type': 'Polygon', 'coordinates': [convert(ring, tx, ty) for ring in c]}
                    else:
                        poly = {'type': 'MultiPolygon', 'coordinates': [[convert(ring, tx, ty) for ring in polyc] for polyc in c]}
                    geom = shape(poly)
                    if geom.is_valid and not geom.is_empty:
                        geoms.append(geom)
                except Exception:
                    continue
    print('river polygons', len(geoms))
    if not geoms:
        raise SystemExit('no river polygons')
    u = unary_union(geoms)
    clip = box(*BBOX)
    u = u.intersection(clip)
    if u.is_empty:
        raise SystemExit('empty after clip')
    u = u.simplify(0.00025, preserve_topology=True)
    fc = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'source': 'OpenStreetMap / OpenFreeMap z11 water', 'class': 'river'},
         'geometry': mapping(u)}]}
    p = OUT / 'yangtze_areas.json'
    p.write_text(json.dumps(fc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('wrote', p, round(p.stat().st_size / 1024, 1), 'KB', 'bounds', u.bounds)

if __name__ == '__main__':
    main()
