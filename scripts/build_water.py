# -*- coding: utf-8 -*-
"""Build the natural-water basemap from Natural Earth 1:10m data.

Replaces the old very-small-scale river/lake layers with the 1:10m river
centerlines and lake polygons, clipped to the atlas region.  A small curated
set of Chinese river/lake labels is added so the major systems read clearly.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.pydeps'))
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union

ADMIN = ROOT / 'data' / 'admin' / 'ne_water'
OUT = ROOT / 'data' / 'out'
OUT.mkdir(parents=True, exist_ok=True)
CLIP = box(70, 15, 140, 55)

RIVER_LABELS = [
    ('长江', 104.5, 29.2, 22), ('长江', 112.2, 30.4, 18), ('长江', 117.0, 31.6, 8),
    ('黄河', 105.0, 36.2, 26), ('黄河', 109.5, 39.6, -28), ('黄河', 110.0, 40.2, 8),
    ('珠江', 112.7, 23.2, 0),
    ('黑龙江', 126.6, 49.6, 18), ('松花江', 127.6, 45.8, 0),
    ('雅鲁藏布江', 88.6, 29.3, 12), ('澜沧江', 98.8, 25.1, 76), ('怒江', 98.8, 27.0, 82),
    ('汉江', 112.2, 32.6, 18), ('淮河', 116.8, 32.9, 0), ('辽河', 122.2, 42.4, 18),
    ('海河', 117.0, 39.2, 8), ('渭河', 108.2, 34.4, 0), ('湘江', 112.5, 27.5, 78),
    ('赣江', 115.5, 28.0, 80), ('闽江', 118.2, 26.2, 34), ('钱塘江', 119.5, 29.5, 42),
    ('塔里木河', 82.0, 40.5, 0), ('额尔齐斯河', 86.5, 47.5, 20),
]
LAKE_LABELS = [
    ('青海湖', 100.2, 36.9), ('鄱阳湖', 116.3, 29.2), ('洞庭湖', 112.9, 29.3),
    ('太湖', 120.2, 31.2), ('洪泽湖', 118.6, 33.3), ('巢湖', 117.4, 31.6),
    ('呼伦湖', 117.4, 48.9), ('纳木错', 90.6, 30.7), ('色林错', 88.9, 31.8),
    ('博斯腾湖', 87.0, 41.9), ('滇池', 102.7, 24.8), ('洱海', 100.2, 25.8),
]

def clean_coords(obj, nd=5):
    if isinstance(obj, (int, float)):
        return round(obj, nd)
    if isinstance(obj, list):
        return [clean_coords(v, nd) for v in obj]
    if isinstance(obj, dict):
        return {k: clean_coords(v, nd) for k, v in obj.items()}
    return obj

def feature(geom, props):
    return {'type': 'Feature', 'properties': props, 'geometry': clean_coords(mapping(geom))}

def main():
    rivers_doc = json.loads((ADMIN / 'ne_10m_rivers_lake_centerlines.geojson').read_text(encoding='utf-8'))
    lakes_doc = json.loads((ADMIN / 'ne_10m_lakes.geojson').read_text(encoding='utf-8'))
    rivers = []
    for f in rivers_doc['features']:
        try:
            g = shape(f['geometry'])
        except Exception:
            continue
        if g.is_empty or not g.intersects(CLIP):
            continue
        g = g.intersection(CLIP)
        if g.is_empty:
            continue
        g = g.simplify(0.00035, preserve_topology=True)
        p = f.get('properties') or {}
        props = {
            'n': p.get('name_zh') or p.get('name') or '',
            'ne': p.get('name_en') or p.get('name') or '',
            'r': p.get('scalerank', 8),
            'w': p.get('strokeweig', 0.2),
            'mz': p.get('min_zoom', 5),
        }
        rivers.append(feature(g, props))
    lakes = []
    for f in lakes_doc['features']:
        try:
            g = shape(f['geometry'])
        except Exception:
            continue
        if g.is_empty or not g.intersects(CLIP):
            continue
        g = g.intersection(CLIP)
        if g.is_empty:
            continue
        g = g.simplify(0.0003, preserve_topology=True)
        p = f.get('properties') or {}
        props = {
            'n': p.get('name_zh') or p.get('name') or '',
            'ne': p.get('name_en') or p.get('name') or '',
            'r': p.get('scalerank', 5),
        }
        lakes.append(feature(g, props))
    rlabels = [{'type': 'Feature', 'properties': {'n': n, 'r': rot, 'kind': 'river'},
                'geometry': {'type': 'Point', 'coordinates': [lon, lat]}}
               for n, lon, lat, rot in RIVER_LABELS]
    llabels = [{'type': 'Feature', 'properties': {'n': n, 'kind': 'lake'},
                'geometry': {'type': 'Point', 'coordinates': [lon, lat]}}
               for n, lon, lat in LAKE_LABELS]
    water = {
        'rivers': {'type': 'FeatureCollection', 'features': rivers},
        'lakes': {'type': 'FeatureCollection', 'features': lakes},
        'riverLabels': {'type': 'FeatureCollection', 'features': rlabels},
        'lakeLabels': {'type': 'FeatureCollection', 'features': llabels},
    }
    p = OUT / 'water.json'
    p.write_text(json.dumps(water, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('rivers', len(rivers), 'lakes', len(lakes), 'labels', len(rlabels), len(llabels))
    print('wrote', p, round(p.stat().st_size / 1024 / 1024, 2), 'MB')

if __name__ == '__main__':
    main()
