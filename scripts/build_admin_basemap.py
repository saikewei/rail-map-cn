# -*- coding: utf-8 -*-
"""Build the precise administrative basemap.

Boundary geometry: 2025 national standard vector map derived from Tianditu,
审图号 GS(2024)0650, distributed publicly by geojson.cn.
Administrative label points: DataV GeoAtlas (province / prefecture / county).
Surrounding land: Natural Earth 1:10m, cropped to the map/inset region.
Rivers & lakes: Natural Earth, existing pocket basemap layers.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.pydeps'))
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union

ADMIN = ROOT / 'data' / 'admin'
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'data' / 'out'
OUT.mkdir(parents=True, exist_ok=True)

CAPITALS = {
    '石家庄市','太原市','呼和浩特市','沈阳市','长春市','哈尔滨市','南京市','杭州市','合肥市',
    '福州市','南昌市','济南市','郑州市','武汉市','长沙市','广州市','南宁市','海口市','成都市',
    '贵阳市','昆明市','拉萨市','西安市','兰州市','西宁市','银川市','乌鲁木齐市',
}

PROVINCE_SHORT = {
    '北京市': '北京', '天津市': '天津', '河北省': '河北', '山西省': '山西',
    '内蒙古自治区': '内蒙古', '辽宁省': '辽宁', '吉林省': '吉林', '黑龙江省': '黑龙江',
    '上海市': '上海', '江苏省': '江苏', '浙江省': '浙江', '安徽省': '安徽',
    '福建省': '福建', '江西省': '江西', '山东省': '山东', '河南省': '河南',
    '湖北省': '湖北', '湖南省': '湖南', '广东省': '广东', '广西壮族自治区': '广西',
    '海南省': '海南', '重庆市': '重庆', '四川省': '四川', '贵州省': '贵州',
    '云南省': '云南', '西藏自治区': '西藏', '陕西省': '陕西', '甘肃省': '甘肃',
    '青海省': '青海', '宁夏回族自治区': '宁夏', '新疆维吾尔自治区': '新疆',
    '台湾省': '台湾', '香港特别行政区': '香港', '澳门特别行政区': '澳门',
}

ETHNIC = ['蒙古', '藏', '彝', '苗', '侗', '布依', '傣', '白', '哈尼', '壮', '瑶', '土家',
          '朝鲜', '哈萨克', '柯尔克孜', '回', '傈僳', '景颇', '拉祜', '佤', '纳西', '羌',
          '满', '土', '达斡尔', '鄂温克', '鄂伦春', '锡伯', '裕固', '东乡', '保安', '撒拉',
          '俄罗斯', '塔吉克', '塔塔尔', '乌孜别克', '门巴', '珞巴', '赫哲', '水', '仫佬',
          '毛南', '京', '高山', '多民族']

def short_admin(name, level):
    s = name.strip()
    if level == 'province':
        return PROVINCE_SHORT.get(s, re.sub(r'(省|市|自治区|特别行政区)$', '', s))
    # strip long tail type first
    s = re.sub(r'(自治州|自治县|自治旗|地区|盟|市辖区|新区|矿区|林区|特区|直辖)$', '', s)
    # for autonomous units: keep the historical toponym before ethnic descriptors
    if level == 'city' or ('自治' in name):
        cut = len(s)
        for marker in ETHNIC:
            i = s.find(marker, 2)
            if i > 0:
                cut = min(cut, i)
        s = s[:cut]
    s = re.sub(r'(市|县|区|旗)$', '', s)
    if not s:
        s = name
    return s

def clean_coords(obj, nd=6):
    if isinstance(obj, (int, float)):
        return round(obj, nd)
    if isinstance(obj, list):
        return [clean_coords(v, nd) for v in obj]
    if isinstance(obj, dict):
        return {k: clean_coords(v, nd) for k, v in obj.items()}
    return obj

def geom_feature(geom, props=None):
    return {'type': 'Feature', 'properties': props or {}, 'geometry': clean_coords(mapping(geom))}

def main():
    print('loading Tianditu standard boundary...')
    d = json.loads((ADMIN / '100000.json').read_text(encoding='utf-8'))
    province_feats = [f for f in d['features'] if f['properties'].get('name') != '境界线']
    boundary_feats = [f for f in d['features'] if f['properties'].get('name') == '境界线']
    print('provinces', len(province_feats), 'boundary lines', len(boundary_feats))
    prov_geoms = [shape(f['geometry']) for f in province_feats]
    # preserve the official province fills, add display metadata
    provinces = []
    for f, g in zip(province_feats, prov_geoms):
        nm = f['properties']['name']
        provinces.append(geom_feature(g, {'name': nm, 'short': PROVINCE_SHORT.get(nm, nm), 'adcode': f['properties'].get('code', '')}))

    print('union boundary...')
    union = unary_union(prov_geoms)
    # 11 m tolerance: far below the visual precision of this map, keeps the file lean
    nation = union.boundary.simplify(0.0001, preserve_topology=True)
    provlines = unary_union([p.boundary.simplify(0.00016, preserve_topology=True) for p in prov_geoms])
    print('nation boundary parts', len(nation.geoms) if hasattr(nation, 'geoms') else 1)
    print('province linework parts', len(provlines.geoms) if hasattr(provlines, 'geoms') else 1)

    print('processing surrounding land...')
    ne = json.loads((ADMIN / 'ne_10m_land.geojson').read_text(encoding='utf-8'))
    clip = box(60, 0, 150, 60)
    land_feats = []
    for f in ne['features']:
        g = shape(f['geometry']).intersection(clip)
        if g.is_empty:
            continue
        g = g.simplify(0.0012, preserve_topology=True)
        land_feats.append(geom_feature(g))
    print('land features', len(land_feats))

    print('building administrative labels...')
    A = json.loads((ADMIN / 'admin_labels.json').read_text(encoding='utf-8'))
    plabels, clabels, xlabels = [], [], []
    for p in A['provinces']:
        plabels.append({
            'type': 'Feature',
            'properties': {'n': PROVINCE_SHORT.get(p['name'], p['name']), 'f': p['name'], 'a': p['adcode'], 'level': 'province'},
            'geometry': {'type': 'Point', 'coordinates': [round(p['lon'], 5), round(p['lat'], 5)]},
        })
    for x in A['cities']:
        if any(k in x['name'] for k in ('直辖县级', '市辖区')):
            continue
        clabels.append({
            'type': 'Feature',
            'properties': {'n': short_admin(x['name'], 'city'), 'f': x['name'], 'a': x['adcode'], 'level': 'city', 'capital': 1 if x['name'] in CAPITALS else 0},
            'geometry': {'type': 'Point', 'coordinates': [round(x['lon'], 5), round(x['lat'], 5)]},
        })
    for x in A['counties']:
        if '直辖' in x['name'] or '市辖区' in x['name']:
            continue
        xlabels.append({
            'type': 'Feature',
            'properties': {'n': short_admin(x['name'], 'county'), 'f': x['name'], 'a': x['adcode'], 'level': 'county'},
            'geometry': {'type': 'Point', 'coordinates': [round(x['lon'], 5), round(x['lat'], 5)]},
        })
    print('labels', len(plabels), len(clabels), len(xlabels))

    # rivers and lakes: keep the pocket layers, crop/round for stable payload size
    rivers = json.loads((RAW / 'rp_web/data/basemap/rivers.json').read_text(encoding='utf-8'))
    lakes = json.loads((RAW / 'rp_web/data/basemap/lakes.json').read_text(encoding='utf-8'))

    out = {
        'land': {'type': 'FeatureCollection', 'features': land_feats},
        'provinces': {'type': 'FeatureCollection', 'features': provinces},
        'provLines': geom_feature(provlines),
        'nation': geom_feature(nation),
        'maritime': {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'name': '境界线'}, 'geometry': clean_coords(f['geometry'])}
            for f in boundary_feats
        ]},
        'rivers': rivers,
        'lakes': lakes,
        'provinceLabels': {'type': 'FeatureCollection', 'features': plabels},
        'cityLabels': {'type': 'FeatureCollection', 'features': clabels},
        'countyLabels': {'type': 'FeatureCollection', 'features': xlabels},
    }
    p = OUT / 'admin_basemap.json'
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('wrote', p, round(p.stat().st_size / 1024 / 1024, 2), 'MB')
    print('审图号 GS(2024)0650 · Tianditu standard vector boundaries')

if __name__ == '__main__':
    main()
