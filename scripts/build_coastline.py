# -*- coding: utf-8 -*-
"""Build a coastline matching the Natural Earth 1:10m land mask.

The old dark outline came from the official province polygons, which still
followed the estuary as land; the fill was clipped to NE land, so the two
disagreed.  This derives the coastline from the same NE land polygon used by
the fill.  Land borders come from NE admin-0 boundary lines, not the coast.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.pydeps'))
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union

OUT = ROOT / 'data' / 'out'
BASE = json.loads((OUT / 'admin_basemap.json').read_text(encoding='utf-8'))
CLIP = box(70, 15, 140, 55)
land = unary_union([shape(f['geometry']) for f in BASE['land']['features']]).intersection(CLIP)
coast = land.boundary.simplify(0.0004, preserve_topology=True)
coast_fc = {'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'properties': {'kind': 'coastline'}, 'geometry': mapping(coast)}
]}
(OUT / 'coastline.json').write_text(json.dumps(coast_fc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

src = json.loads((ROOT / 'data' / 'admin' / 'ne_coast' / 'ne_10m_admin_0_boundary_lines_land.geojson').read_text(encoding='utf-8'))
feats = []
for f in src['features']:
    g = shape(f['geometry'])
    if g.is_empty or not g.intersects(CLIP):
        continue
    g = g.intersection(CLIP)
    if g.is_empty:
        continue
    feats.append({'type': 'Feature', 'properties': {'kind': 'land border'}, 'geometry': mapping(g.simplify(0.0004, preserve_topology=True))})
(OUT / 'nation_borders.json').write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('coastline KB', (OUT / 'coastline.json').stat().st_size // 1024, 'borders', len(feats), 'KB', (OUT / 'nation_borders.json').stat().st_size // 1024)
