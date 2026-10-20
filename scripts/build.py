# -*- coding: utf-8 -*-
import base64, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "out"
TPL = (ROOT / "src" / "index.template.html").read_text(encoding="utf-8")
base_doc = json.loads((OUT / "admin_basemap.json").read_text(encoding="utf-8"))
water = json.loads((OUT / "water.json").read_text(encoding="utf-8"))
water["riverAreas"] = json.loads((OUT / "yangtze_areas.json").read_text(encoding="utf-8"))
for _f in water["riverAreas"]["features"]:
    _f.setdefault("properties", {}).setdefault("n", "yangtze_lower")
_major = json.loads((OUT / "major_water_areas.json").read_text(encoding="utf-8"))
water["riverAreas"]["features"].extend(_major["features"])
base_doc["rivers"] = water["rivers"]
base_doc["lakes"] = water["lakes"]
base_doc["riverLabels"] = water["riverLabels"]
base_doc["lakeLabels"] = water["lakeLabels"]
base_doc["riverAreas"] = water["riverAreas"]
base_doc["chinaLand"] = json.loads((OUT / "china_land.json").read_text(encoding="utf-8"))
base_doc["nationLandBorders"] = json.loads((OUT / "nation_land_borders.json").read_text(encoding="utf-8"))
base_doc["provLandLines"] = json.loads((OUT / "prov_land_lines.json").read_text(encoding="utf-8"))
atlas = {
    "meta": json.loads((OUT / "meta.json").read_text(encoding="utf-8")),
    "lines": json.loads((OUT / "line_index.json").read_text(encoding="utf-8"))["lines"],
    "stations": json.loads((OUT / "stations.json").read_text(encoding="utf-8")),
    "rail": json.loads((OUT / "rail.json").read_text(encoding="utf-8")),
    "lineLabels": json.loads((OUT / "line_labels.json").read_text(encoding="utf-8")),
    "basemap": base_doc,
    "junctions": json.loads((OUT / "junctions.json").read_text(encoding="utf-8")),
}
font_names = ["0-255", "256-511", "8192-8447", "12288-12543", "65280-65535"]
glyphs = {name: base64.b64encode((ROOT / "vendor" / "fonts" / "noto" / f"{name}.pbf").read_bytes()).decode("ascii") for name in font_names}
maplibre_js = (ROOT / "vendor" / "maplibre-gl.js").read_text(encoding="utf-8")
maplibre_css = (ROOT / "vendor" / "maplibre-gl.css").read_text(encoding="utf-8")
atlas_css = (ROOT / "src" / "atlas.css").read_text(encoding="utf-8")
atlas_js = (ROOT / "src" / "atlas.js").read_text(encoding="utf-8")
data_json = json.dumps(atlas, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
glyph_json = json.dumps(glyphs, ensure_ascii=False, separators=(",", ":"))
js_escape = lambda s: s.replace("</script>", "<\\/script>")
html = TPL
for token, content in [
    ("/*__MAPLIBRE_CSS__*/", maplibre_css),
    ("/*__ATLAS_CSS__*/", atlas_css),
    ("/*__MAPLIBRE_JS__*/", js_escape(maplibre_js)),
    ("/*__ATLAS_JS__*/", js_escape(atlas_js)),
    ("/*__ATLAS_DATA__*/", data_json),
    ("/*__GLYPHS__*/", glyph_json),
]:
    html = html.replace(token, content, 1)
for name in ("map.html", "全国客运铁路地图.html"):
    (ROOT / name).write_text(html, encoding="utf-8")
(ROOT / "index.html").write_text((ROOT / "src" / "landing.html").read_text(encoding="utf-8"), encoding="utf-8")
print("built", len(html.encode("utf-8")) / 1024 / 1024, "MB")
