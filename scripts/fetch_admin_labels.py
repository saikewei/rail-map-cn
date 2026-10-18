# -*- coding: utf-8 -*-
"""Collect province / prefecture / county label points from DataV GeoAtlas.

Boundary geometry comes from the Tianditu-derived, map-approved GeoJSON
(`data/admin/100000.json`); DataV is used only for administrative label points
and hierarchy names, because its three-level label attributes are convenient.
"""
import json, os, re, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN = ROOT / 'data' / 'admin'
CACHE = ADMIN / 'cache'
CACHE.mkdir(parents=True, exist_ok=True)
BASE = 'https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json'
HEADERS = {'User-Agent': 'rail-atlas-research/1.0 (local study use)'}

def fetch(adcode, force=False):
    path = CACHE / f'{adcode}_full.json'
    if path.exists() and not force:
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(BASE.format(adcode=adcode), headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            obj = json.loads(data)
            path.write_bytes(data)
            return obj
        except Exception as e:
            last = e
            time.sleep(1.2 * (attempt + 1))
    print('FAIL', adcode, last, file=sys.stderr)
    return None

def labels_from_province(prov):
    """Return province children plus classification."""
    adcode = int(prov['properties']['adcode'])
    d = fetch(adcode)
    if not d:
        return [], []
    cities, counties = [], []
    for f in d.get('features', []):
        p = f.get('properties') or {}
        code = p.get('adcode')
        if not code:
            continue
        name = p.get('name') or ''
        center = p.get('center') or p.get('centroid')
        if not center:
            continue
        lon, lat = float(center[0]), float(center[1])
        rec = {'name': name, 'adcode': int(code), 'lon': lon, 'lat': lat,
               'parent': adcode, 'level': 'city' if int(code) % 100 == 0 else 'county'}
        if rec['level'] == 'city':
            cities.append(rec)
        else:
            counties.append(rec)
    return cities, counties

def main():
    provinces = json.loads((ADMIN / '100000_full.json').read_text(encoding='utf-8'))['features']
    # include all 34 administrative province-level polygons
    plist = []
    for f in provinces:
        p = f.get('properties') or {}
        if not p.get('adcode'):
            continue
        center = p.get('center') or p.get('centroid')
        if not center:
            continue
        plist.append({'name': p.get('name', ''), 'adcode': int(p['adcode']),
                      'lon': float(center[0]), 'lat': float(center[1]), 'parent': 100000,
                      'level': 'province'})
    print('provinces', len(plist))
    cities, counties = [], []
    # First level: province children
    for p in plist:
        cs, ds = labels_from_province({'properties': {'adcode': p['adcode']}})
        cities.extend(cs)
        counties.extend(ds)
    print('city labels', len(cities), 'direct county labels', len(counties))
    # Second level: every prefecture
    city_codes = sorted(set(c['adcode'] for c in cities))
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch, code): code for code in city_codes}
        done = 0
        for fut in as_completed(futs):
            code = futs[fut]
            d = fut.result()
            done += 1
            if done % 25 == 0 or done == len(futs):
                print('fetch city files', done, '/', len(futs), flush=True)
            if not d:
                continue
            for f in d.get('features', []):
                p = f.get('properties') or {}
                center = p.get('center') or p.get('centroid')
                if center and p.get('adcode'):
                    counties.append({'name': p.get('name', ''), 'adcode': int(p['adcode']),
                                     'lon': float(center[0]), 'lat': float(center[1]),
                                     'parent': code, 'level': 'county'})
    # de-duplicate by adcode
    def dedupe(items):
        seen = set(); out = []
        for x in items:
            if x['adcode'] in seen:
                continue
            seen.add(x['adcode']); out.append(x)
        return out
    plist = dedupe(plist); cities = dedupe(cities); counties = dedupe(counties)
    print('final counts', len(plist), len(cities), len(counties))
    out = {'provinces': plist, 'cities': cities, 'counties': counties}
    (ADMIN / 'admin_labels.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('wrote', (ADMIN / 'admin_labels.json'), (ADMIN / 'admin_labels.json').stat().st_size, 'bytes')

if __name__ == '__main__':
    main()
