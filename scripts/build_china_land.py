# -*- coding: utf-8 -*-
"""Clip the official province polygons to one coherent 1:10m land mask.

The Tianditu province polygons include some estuary water (notably the
Yangtze mouth), so using them directly as the land fill made the estuary look
like land.  The Natural Earth 1:10m land polygon has one continuous coastline
with the estuary open; intersecting the two gives a single land surface and
removes the need to patch the coast with ocean rectangles.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.pydeps'))
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

OUT = ROOT / 'data' / 'out'
base = json.loads((OUT / 'admin_basemap.json').read_text(encoding='utf-8'))
land = unary_union([shape(f['geometry']) for f in base['land']['features']])
feats = []
for f in base['provinces']['features']:
    try:
        g = shape(f['geometry']).buffer(0).intersection(land)
        if g.is_empty:
            continue
        g = g.simplify(0.0008, preserve_topology=True)
        feats.append({'type': 'Feature', 'properties': f.get('properties', {}), 'geometry': mapping(g)})
    except Exception:
        continue
fc = {'type': 'FeatureCollection', 'features': feats}
p = OUT / 'china_land.json'
p.write_text(json.dumps(fc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('china land features', len(feats), 'MB', round(p.stat().st_size/1024/1024, 2))
