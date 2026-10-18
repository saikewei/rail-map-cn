# -*- coding: utf-8 -*-
"""Keep the official national land borders, drop the coast stroke.

The GS(2024)0650 national boundary contains both land borders and coastline.
The coastline is already represented by the land/sea fill; drawing the
official coastline stroke on top of the NE-based land mask caused the visible
mismatch.  Remove only the parts of the official national line that lie on
the physical coastline, preserving all land-border sections.
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
nation = shape(BASE['nation']['geometry'])
diff = nation.difference(coast).simplify(0.0004, preserve_topology=True)
# Closed rings are island/coastal loops.  Short open remnants in the sea
# (islands absent from the NE land mask) are dropped as well.
from shapely.geometry import MultiLineString
parts = []
for g in diff.geoms:
    if g.is_ring or g.length < 0.12:
        continue
    if land.distance(g) > 0.035:
        continue
    parts.append(g)
kept = MultiLineString(parts)
fc = {'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'properties': {'kind': 'land border'}, 'geometry': mapping(kept)}
]}
p = OUT / 'nation_land_borders.json'
p.write_text(json.dumps(fc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('kept land borders', kept.geom_type, 'KB', round(p.stat().st_size/1024,1))
