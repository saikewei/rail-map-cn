# -*- coding: utf-8 -*-
"""Province boundaries with the coastal segments removed.

The province line dataset includes the outer coastline as well as internal
borders.  Once the national coast stroke is removed, the dashed province
coastline still reads as a second coast outline.  Clip only the parts within
a short buffer of the physical coastline, keeping all internal land borders.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.pydeps'))
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
OUT = ROOT / 'data' / 'out'
BASE = json.loads((OUT / 'admin_basemap.json').read_text(encoding='utf-8'))
land = unary_union([shape(f['geometry']) for f in BASE['land']['features']])
coast = land.boundary.buffer(0.08)
prov = shape(BASE['provLines']['geometry'])
diff = prov.difference(coast).simplify(0.0004, preserve_topology=True)
from shapely.geometry import MultiLineString
parts = []
for g in diff.geoms:
    if g.is_ring or g.length < 0.08:
        continue
    if land.distance(g) > 0.035:
        continue
    parts.append(g)
kept = MultiLineString(parts)
fc = {'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'properties': {'kind': 'province land borders'}, 'geometry': mapping(kept)}
]}
p = OUT / 'prov_land_lines.json'
p.write_text(json.dumps(fc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('kept province land lines', kept.geom_type, 'KB', round(p.stat().st_size/1024,1))
