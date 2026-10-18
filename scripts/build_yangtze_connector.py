# -*- coding: utf-8 -*-
"""Bridge the lower-Yangtze water polygon to the sea.

The OSM river-surface polygons stop at the mapped river mouth around
121.93E, leaving a narrow land-coloured seam before the sea.  A short buffer
of the existing river surface, clipped to the mouth, removes that seam
without inventing a long channel.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.pydeps'))
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union

OUT = ROOT / 'data' / 'out'
src = json.loads((OUT / 'yangtze_areas.json').read_text(encoding='utf-8'))
geoms = [shape(f['geometry']) for f in src['features']]
u = unary_union(geoms)
conn = u.buffer(0.22, join_style=2).intersection(box(121.55, 30.7, 122.55, 32.3))
conn = conn.simplify(0.0003, preserve_topology=True)
fc = {'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'properties': {'n': 'yangtze_mouth_connector', 'src': 'buffer of OSM lower Yangtze water'}, 'geometry': mapping(conn)}
]}
p = OUT / 'yangtze_mouth_connector.json'
p.write_text(json.dumps(fc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('connector bounds', conn.bounds, 'KB', round(p.stat().st_size/1024,1))
