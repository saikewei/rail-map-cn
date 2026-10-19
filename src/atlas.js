(() => {
'use strict';

const DATA = window.ATLAS;
const { meta, lines, stations, rail, basemap, junctions } = DATA;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n) => Number(n || 0).toLocaleString('zh-CN');

const SPEEDS = {
  350: { color: '#b33627', label: '350', unit: 'km/h', name: '高速动车', desc: '最高运营等级' },
  300: { color: '#d2602c', label: '300', unit: 'km/h', name: '高速铁路', desc: '高速客运专线' },
  250: { color: '#d0a029', label: '250', unit: 'km/h', name: '快速客运', desc: '高速 / 城际' },
  200: { color: '#4c8b61', label: '200', unit: 'km/h', name: '快速铁路', desc: '客货共线 / 城际' },
  160: { color: '#5f4b7a', label: '160', unit: 'km/h', name: '客货共线', desc: '普速干线' },
  140: { color: '#80658a', label: '140', unit: 'km/h', name: '快速干线', desc: '设计 140' },
  120: { color: '#8d607f', label: '120', unit: 'km/h', name: '普速铁路', desc: '区域干线' },
  80:  { color: '#9c9183', label: '80',  unit: 'km/h', name: '支线慢行', desc: '支线 / 慢车' },
};
const SPEED_ORDER = [350, 300, 250, 200, 160, 140, 120, 80];
const TIER_ZOOM = { 1: 2.88, 2: 4.42, 3: 5.95, 4: 7.4 };
const STATION_DOT_ZOOM = { 1: 2.95, 2: 4.7, 3: 6.1, 4: 7.7 };
const STATION_LABEL_ZOOM = { 1: 4.25, 2: 5.2, 3: 6.5, 4: 7.95 };
const HUB_NAME = { 1: '全国性枢纽', 2: '区域枢纽', 3: '重要车站', 4: '普通车站' };
const C = {
  sea: '#dae6e3', land: '#ece6d9', china: '#f8f3e8', lake: '#c5dcdb', river: '#a8c7ca',
  province: 'rgba(116,101,81,.52)', nation: '#6d5a45', city: '#73786f', cityHalo: '#f8f3e7',
  provinceLabel: '#81745d', adminCity: '#5d6156', adminCounty: '#6f6c60', adminDot: '#7c7668',
  lineHalo: '#f8f3e7', station: '#fdf8ec', stationStroke: '#262a25',
  stationLabel: '#30342d', stationHalo: '#faf6ea', accent: '#ad3a28',
};

const lineById = new Map(lines.map(l => [l.id, l]));
const lineByName = new Map(lines.map(l => [l.name, l]));
const stationById = new Map(stations.map((s, i) => [s.id != null ? s.id : i, s]));
const stationByName = new Map(stations.map(s => [s.name, s]));
const placeText = (s) => {
  if (!s) return '';
  const p = String(s.province || '').replace(/(省|市|自治区|特别行政区)$/, '');
  const c = String(s.city || '');
  if (!p) return c;
  if (!c) return s.province;
  if (p === c || String(s.province).includes(c) || c.includes(p)) return c;
  return `${s.province} · ${c}`;
};
const speedCount = {};
for (const l of lines) speedCount[l.speed] = (speedCount[l.speed] || 0) + 1;
const visibleSpeeds = new Set(SPEED_ORDER);
const state = { selectedLine: null, selectedStation: null, lineLabels: true, stationLayer: true, junctionLayer: true, adminLevels: { province: true, city: true, county: false }, provinceBorders: true, activeTab: 'overview', lineType: 'all', lineQuery: '', searchIndex: -1, focusReturn: null };
const ADMIN_LAYERS = { province: ['province-labels', 'taiwan-label'], city: ['capital-labels', 'capital-city-dots', 'city-labels', 'admin-city-dots'], county: ['county-labels', 'admin-county-dots'] };

/* ---------------------------------------------------------------- glyphs */
function b64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const len = bin.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}
maplibregl.addProtocol('glyph', async (params) => {
  const m = String(params.url).match(/glyph:\/\/([^/]+)\/(.+)\.pbf/);
  if (m && window.GLYPHS[m[2]]) return { data: b64ToArrayBuffer(window.GLYPHS[m[2]]) };
  return { data: new ArrayBuffer(0) };
});

/* ---------------------------------------------------------------- helpers */
function lineColor(line) { return (SPEEDS[line.speed] || SPEEDS[120]).color; }
function stationLines(s) {
  return (s.lines || []).filter(x => lineByName.has(x.name));
}
function stationGeoJSON(sel) {
  if (!sel) return { type: 'FeatureCollection', features: [] };
  return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { name: sel.name }, geometry: { type: 'Point', coordinates: [sel.lon, sel.lat] } }] };
}
function lineGeoJSON(id) {
  const feats = rail.features.filter(f => f.properties.k === id);
  return { type: 'FeatureCollection', features: feats };
}
function lineBounds(id) {
  const b = new maplibregl.LngLatBounds();
  for (const f of rail.features) {
    if (f.properties.k !== id) continue;
    for (const line of f.geometry.coordinates) for (const p of line) b.extend(p);
  }
  return b;
}
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toast._tm); toast._tm = setTimeout(() => t.classList.remove('show'), 2100);
}
function railFilter(speed) {
  return ['all', ['==', ['get', 's'], speed], ['in', ['get', 's'], ['literal', [...visibleSpeeds]]]];
}
function optionHTML(speed) {
  const m = SPEEDS[speed];
  return `<span class="swatch" style="--c:${m.color}"></span><span class="sp-label"><span class="sp-val">${m.label}</span><span class="sp-unit">${m.unit}</span><span class="sp-name">${m.name}</span></span><span class="sp-count"><b>${speedCount[speed] || 0}</b> 条</span>`;
}

/* ---------------------------------------------------------------- map */
const isNarrow = () => window.innerWidth <= 880;
const FIT_BOUNDS = [[73.3, 18.0], [135.15, 53.6]];
const GLYPH_FAMILY = '"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif';

const style = {
  version: 8,
  name: 'China Passenger Rail Atlas',
  glyphs: 'glyph://{fontstack}/{range}.pbf',
  sources: {
    land: { type: 'geojson', data: basemap.land },
    provinces: { type: 'geojson', data: basemap.provinces },
    chinaLand: { type: 'geojson', data: basemap.chinaLand },
    nationLandBorders: { type: 'geojson', data: basemap.nationLandBorders },
    provLandLines: { type: 'geojson', data: basemap.provLandLines },
    provLines: { type: 'geojson', data: basemap.provLines },
    nation: { type: 'geojson', data: basemap.nation },
    maritime: { type: 'geojson', data: basemap.maritime },
    rivers: { type: 'geojson', data: basemap.rivers },
    lakes: { type: 'geojson', data: basemap.lakes },
    riverAreas: { type: 'geojson', data: basemap.riverAreas },
    riverLabels: { type: 'geojson', data: basemap.riverLabels },
    lakeLabels: { type: 'geojson', data: basemap.lakeLabels },
    provinceLabels: { type: 'geojson', data: basemap.provinceLabels },
    taiwanLabel: { type: 'geojson', data: { type: 'Feature', properties: { n: '台湾' }, geometry: { type: 'Point', coordinates: [121.0, 23.7] } } },
    cityLabels: { type: 'geojson', data: basemap.cityLabels },
    countyLabels: { type: 'geojson', data: basemap.countyLabels },
    junctionLinks: { type: 'geojson', data: (junctions && junctions.links) || { type: 'FeatureCollection', features: [] } },
    junctionNodes: { type: 'geojson', data: (junctions && junctions.nodes) || { type: 'FeatureCollection', features: [] } },
    rail: { type: 'geojson', data: rail },
    stations: { type: 'geojson', data: {
      type: 'FeatureCollection',
      features: stations.map(s => ({ type: 'Feature', properties: { id: s.id, name: s.name, rank: s.rank, tier: s.tier, city: s.city }, geometry: { type: 'Point', coordinates: [s.lon, s.lat] } }))
    } },
    selection: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
    selectedStation: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': C.sea } },
    { id: 'land-fill', type: 'fill', source: 'land', paint: { 'fill-color': C.land, 'fill-opacity': 1 } },
    { id: 'china-fill', type: 'fill', source: 'chinaLand', paint: { 'fill-color': C.china, 'fill-opacity': 1 } },
    { id: 'river-areas', type: 'fill', source: 'riverAreas', paint: { 'fill-color': C.sea, 'fill-opacity': 1 } },
    { id: 'lakes', type: 'fill', source: 'lakes', paint: { 'fill-color': C.sea, 'fill-opacity': 1 } },
    { id: 'lake-outline', type: 'line', source: 'lakes', paint: { 'line-color': '#98b9b8', 'line-width': ['interpolate', ['linear'], ['zoom'], 3, .35, 7, .7, 12, 1.1], 'line-opacity': .55 } },
    { id: 'river-casing', type: 'line', source: 'rivers', layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': C.lineHalo, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, ['+', .5, ['*', ['get', 'w'], .7]], 7, ['+', .8, ['*', ['get', 'w'], 1.2]], 12, ['+', 1.2, ['*', ['get', 'w'], 1.8]]], 'line-opacity': .65 } },
    { id: 'rivers', type: 'line', source: 'rivers', layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: {
        'line-color': ['case', ['<=', ['get', 'r'], 3], '#6d9ca1', ['<=', ['get', 'r'], 5], '#87b2b5', '#a7c6c8'],
        'line-width': ['interpolate', ['linear'], ['zoom'], 3, ['+', .25, ['*', ['get', 'w'], .55]], 6, ['+', .4, ['*', ['get', 'w'], 1.0]], 10, ['+', .7, ['*', ['get', 'w'], 1.8]]],
        'line-opacity': ['case', ['<=', ['get', 'r'], 3], .95, ['<=', ['get', 'r'], 5], .8, .58],
      } },
    { id: 'rivers-major', type: 'line', source: 'rivers', layout: { 'line-join': 'round', 'line-cap': 'round' },
      filter: ['any', ['<=', ['get', 'r'], 3], ['in', ['get', 'n'], ['literal', ['长江','黄河','黑龙江','松花江','珠江','雅鲁藏布江','澜沧江','怒江','汉江','淮河','辽河','海河','渭河','湘江','赣江','闽江','钱塘江','塔里木河','额尔齐斯河']]]],
      paint: { 'line-color': '#5b8d93', 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 1.5, 6, 2.4, 10, 3.8], 'line-opacity': .92 } },
    { id: 'prov-lines', type: 'line', source: 'provLandLines', paint: { 'line-color': C.province, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, .55, 8, 1.05, 12, 1.5], 'line-dasharray': [3, 2.5], 'line-opacity': .9 } },
    { id: 'nation-line', type: 'line', source: 'nationLandBorders', paint: { 'line-color': C.nation, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 1.25, 8, 2.1, 12, 2.8], 'line-opacity': .98 } },
    { id: 'maritime-lines', type: 'line', source: 'maritime', paint: { 'line-color': C.nation, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 1.1, 8, 1.7], 'line-opacity': .93 } },
    { id: 'capital-city-dots', type: 'circle', source: 'cityLabels', minzoom: 3.25, maxzoom: 6.0, filter: ['==', ['get', 'capital'], 1], paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 3.25, 1.1, 5.2, 1.8], 'circle-color': C.adminDot, 'circle-opacity': .45 } },
    { id: 'admin-city-dots', type: 'circle', source: 'cityLabels', minzoom: 6.0, maxzoom: 10.6, paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5.2, 1.4, 8, 2.1, 11, 2.6], 'circle-color': C.adminDot, 'circle-opacity': .5 } },
    { id: 'admin-county-dots', type: 'circle', source: 'countyLabels', minzoom: 6.3, maxzoom: 12.5, paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 6.3, 1.0, 10, 1.7], 'circle-color': C.adminDot, 'circle-opacity': .4 } },

    { id: 'rail-casing', type: 'line', source: 'rail', filter: ['in', ['get', 's'], ['literal', [...visibleSpeeds]]], layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': C.lineHalo, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 1.55, 5, 2.3, 8, 4.2, 11, 6], 'line-opacity': .93 } },
    ...SPEED_ORDER.map(speed => ({
      id: 'rail-' + speed, type: 'line', source: 'rail', filter: railFilter(speed),
      layout: { 'line-join': 'round', 'line-cap': 'round', 'line-sort-key': speed },
      paint: {
        'line-color': SPEEDS[speed].color,
        'line-width': ['interpolate', ['linear'], ['zoom'],
          3, speed >= 350 ? 1.05 : speed >= 300 ? .96 : speed >= 250 ? .86 : speed >= 200 ? .75 : speed >= 160 ? .68 : speed >= 140 ? .61 : speed >= 120 ? .56 : .48,
          5, speed >= 350 ? 1.85 : speed >= 300 ? 1.7 : speed >= 250 ? 1.52 : speed >= 200 ? 1.33 : speed >= 160 ? 1.2 : speed >= 140 ? 1.08 : speed >= 120 ? 1.0 : .86,
          8, speed >= 350 ? 4.1 : speed >= 300 ? 3.8 : speed >= 250 ? 3.4 : speed >= 200 ? 3.0 : speed >= 160 ? 2.7 : speed >= 140 ? 2.45 : speed >= 120 ? 2.25 : 1.95,
          11, speed >= 350 ? 6.0 : speed >= 300 ? 5.6 : speed >= 250 ? 5.0 : speed >= 200 ? 4.4 : speed >= 160 ? 3.9 : speed >= 140 ? 3.55 : speed >= 120 ? 3.25 : 2.8,
        ],
        'line-opacity': speed >= 160 ? .97 : .92,
      },
    })),
    { id: 'rail-hit', type: 'line', source: 'rail', filter: ['in', ['get', 's'], ['literal', [...visibleSpeeds]]], layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': 'rgba(0,0,0,0)', 'line-width': 14, 'line-opacity': .01 } },
    { id: 'selection-glow', type: 'line', source: 'selection', layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': '#0f1712', 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 5, 8, 12], 'line-opacity': .14, 'line-blur': 3 } },
    { id: 'selection-line', type: 'line', source: 'selection', layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': '#242722', 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 1.6, 8, 3.2], 'line-opacity': .8, 'line-dasharray': [1.5, 2.5] } },

    ...[1, 2, 3, 4].map(tier => ({ id: 'station-ring-' + tier, type: 'circle', source: 'stations', minzoom: STATION_DOT_ZOOM[tier], filter: ['==', ['get', 'tier'], tier], paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, tier === 1 ? 5.5 : 3.5, 8, tier === 1 ? 8.5 : 5.4, 12, tier === 1 ? 10 : 6], 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#29302a', 'circle-stroke-width': .6, 'circle-stroke-opacity': tier === 1 ? .42 : .18 } })),
    ...[1, 2, 3, 4].map(tier => ({ id: 'station-dot-' + tier, type: 'circle', source: 'stations', minzoom: STATION_DOT_ZOOM[tier], filter: ['==', ['get', 'tier'], tier], paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, tier === 1 ? 3.1 : tier === 2 ? 2.2 : 1.5, 8, tier === 1 ? 5.0 : tier === 2 ? 3.8 : 2.9, 12, tier === 1 ? 6.5 : tier === 2 ? 4.6 : 3.5], 'circle-color': tier <= 2 ? C.station : '#f5efe2', 'circle-stroke-color': tier === 1 ? C.stationStroke : '#7f7768', 'circle-stroke-width': tier === 1 ? 1.25 : tier === 2 ? .9 : .6 } })),
    { id: 'station-selected-ring', type: 'circle', source: 'selectedStation', paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 10, 10, 15], 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': C.accent, 'circle-stroke-width': 1.3, 'circle-stroke-opacity': .8 } },
    { id: 'station-selected-dot', type: 'circle', source: 'selectedStation', paint: { 'circle-radius': 4.2, 'circle-color': C.accent, 'circle-stroke-color': '#fff9ed', 'circle-stroke-width': 1.4 } },

    { id: 'junction-links', type: 'line', source: 'junctionLinks', minzoom: 9.2,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': '#8a7e6b', 'line-width': ['interpolate', ['linear'], ['zoom'], 9.2, .45, 14, .7], 'line-opacity': .38, 'line-dasharray': [1.2, 2.8] } },
    { id: 'junction-nodes-major', type: 'circle', source: 'junctionNodes', minzoom: 7.5,
      filter: ['>=', ['get', 'c'], 3],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 7.5, 4.2, 11, 6.0, 16, 8.5], 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#7a674e', 'circle-stroke-width': .8, 'circle-opacity': .5 } },
    { id: 'junction-nodes-minor', type: 'circle', source: 'junctionNodes', minzoom: 10.5,
      filter: ['==', ['get', 'c'], 2],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 10.5, 3.3, 16, 5.0], 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#8d7e66', 'circle-stroke-width': .65, 'circle-opacity': .42 } },

    { id: 'county-labels', type: 'symbol', source: 'countyLabels', minzoom: 6.3, maxzoom: 12.5,
      layout: { 'text-field': ['get', 'n'], 'text-font': ['noto'], 'text-size': ['interpolate', ['linear'], ['zoom'], 6.3, 8.9, 9, 9.7, 12, 10.5], 'text-variable-anchor': ['top', 'bottom', 'left', 'right'], 'text-radial-offset': .32, 'text-padding': 1.2, 'symbol-sort-key': ['get', 'a'] },
      paint: { 'text-color': C.adminCounty, 'text-halo-color': C.lineHalo, 'text-halo-width': 1.15, 'text-opacity': .95 } },
    { id: 'city-labels', type: 'symbol', source: 'cityLabels', minzoom: 6.0, maxzoom: 10.6,
      layout: { 'text-field': ['get', 'n'], 'text-font': ['noto'], 'text-size': ['interpolate', ['linear'], ['zoom'], 5.2, 10.2, 7, 11.0, 10.6, 11.8], 'text-variable-anchor': ['top', 'bottom', 'left', 'right'], 'text-radial-offset': .42, 'text-padding': 1.8, 'symbol-sort-key': ['get', 'a'] },
      paint: { 'text-color': C.adminCity, 'text-halo-color': C.lineHalo, 'text-halo-width': 1.35, 'text-opacity': 1 } },
    { id: 'capital-labels', type: 'symbol', source: 'cityLabels', minzoom: 3.25, maxzoom: 6.0,
      filter: ['==', ['get', 'capital'], 1],
      layout: { 'text-field': ['get', 'n'], 'text-font': ['noto'], 'text-size': ['interpolate', ['linear'], ['zoom'], 3.25, 9.6, 6.0, 11.0], 'text-variable-anchor': ['top', 'bottom', 'left', 'right'], 'text-radial-offset': .38, 'text-padding': 1.8, 'symbol-sort-key': ['get', 'a'] },
      paint: { 'text-color': C.adminCity, 'text-halo-color': C.lineHalo, 'text-halo-width': 1.35, 'text-opacity': .98 } },
    { id: 'province-labels', type: 'symbol', source: 'provinceLabels', minzoom: 2.85, maxzoom: 5.05,
      filter: ['!=', ['get', 'a'], 710000],
      layout: { 'text-field': ['get', 'n'], 'text-font': ['noto'], 'text-size': ['interpolate', ['linear'], ['zoom'], 3, 13.2, 5.5, 15.2], 'text-letter-spacing': .26, 'text-padding': 6, 'text-allow-overlap': false, 'symbol-sort-key': ['get', 'a'] },
      paint: { 'text-color': C.provinceLabel, 'text-halo-color': C.lineHalo, 'text-halo-width': 1.55, 'text-opacity': .96 } },
    { id: 'taiwan-label', type: 'symbol', source: 'taiwanLabel', minzoom: 2.85, maxzoom: 5.05,
      layout: { 'text-field': ['get', 'n'], 'text-font': ['noto'], 'text-size': ['interpolate', ['linear'], ['zoom'], 3, 13.2, 5.5, 15.2], 'text-letter-spacing': .26, 'text-allow-overlap': true, 'text-padding': 2, 'symbol-sort-key': 0 },
      paint: { 'text-color': C.provinceLabel, 'text-halo-color': C.lineHalo, 'text-halo-width': 1.55, 'text-opacity': .96 } },
    { id: 'river-labels', type: 'symbol', source: 'riverLabels', minzoom: 3.1, maxzoom: 7.4,
      filter: ['!', ['in', ['get', 'n'], ['literal', ['长江', '黄河', '珠江', '黑龙江', '雅鲁藏布江', '钱塘江']]]],
      layout: { 'text-field': ['get', 'n'], 'text-font': ['noto'], 'text-size': ['interpolate', ['linear'], ['zoom'], 3.1, 9.5, 6.5, 12], 'text-letter-spacing': .1, 'text-rotate': ['get', 'r'], 'text-padding': 2, 'text-allow-overlap': true },
      paint: { 'text-color': '#4d7c82', 'text-halo-color': C.lineHalo, 'text-halo-width': 1.2, 'text-opacity': .95 } },
    { id: 'lake-labels', type: 'symbol', source: 'lakeLabels', minzoom: 4.0, maxzoom: 8.2,
      layout: { 'text-field': ['get', 'n'], 'text-font': ['noto'], 'text-size': ['interpolate', ['linear'], ['zoom'], 4.0, 8.5, 7.5, 10.2], 'text-letter-spacing': .06, 'text-padding': 2.5, 'text-allow-overlap': false },
      paint: { 'text-color': '#70999b', 'text-halo-color': C.lineHalo, 'text-halo-width': 1.1, 'text-opacity': .82 } },

  ],
};

const map = new maplibregl.Map({
  container: 'map', style, center: [104.3, 35.2], zoom: 3.2,
  minZoom: 2.8, maxZoom: 16.5, maxPitch: 0, attributionControl: false,
  localIdeographFontFamily: GLYPH_FAMILY, renderWorldCopies: false,
  dragRotate: false, pitchWithRotate: false, touchPitch: false,
  antialias: true, fadeDuration: 140,
});
map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: 'metric' }), 'bottom-right');
map.touchZoomRotate.disableRotation();
map.keyboard.disableRotation();
map.on('error', (e) => console.warn('[map]', e && e.error ? e.error.message : e));

function fitOverview(animate = true) {
  if (mapReady) map.setPadding({ top: 0, bottom: 0, left: 0, right: 0 });
  const pad = isNarrow()
    ? { top: 18, bottom: Math.max(280, window.innerHeight * .47), left: 12, right: 12 }
    : { top: 24, bottom: 20, left: window.innerWidth <= 1020 ? 382 : 426, right: 26 };
  map.fitBounds(FIT_BOUNDS, { padding: pad, duration: animate ? 950 : 0, maxZoom: 5 });
}
let mapReady = false;
map.on('load', () => {
  mapReady = true;
  applyLineFilters();
  applyLabelVisibility();
  applyStationVisibility();
  applyAdminVisibility();
  applyProvinceBordersVisibility();
  applyJunctionVisibility();
  fitOverview(false);
  initInset();
  initLineLabelOverlay();
  scheduleLineLabels();
  setTimeout(() => map.resize(), 250);
});

window.addEventListener('resize', () => {
  if (mapReady) map.resize();
});

/* ---------------------------------------------------------------- filters */
function applyLineFilters() {
  if (!mapReady) return;
  for (const speed of SPEED_ORDER) map.setFilter('rail-' + speed, railFilter(speed));
  map.setFilter('rail-casing', ['in', ['get', 's'], ['literal', [...visibleSpeeds]]]);
  map.setFilter('rail-hit', ['in', ['get', 's'], ['literal', [...visibleSpeeds]]]);
  $$('#speedLegend .speed-row').forEach(btn => {
    btn.classList.toggle('off', !visibleSpeeds.has(Number(btn.dataset.speed)));
    btn.setAttribute('aria-pressed', visibleSpeeds.has(Number(btn.dataset.speed)) ? 'true' : 'false');
  });
  $$('#mapLegend .mleg').forEach(btn => btn.classList.toggle('off', !visibleSpeeds.has(Number(btn.dataset.speed))));
  syncSpeedFilter();
  if ($('#lineList')) renderLineList();
  scheduleLineLabels();
}
function applyLabelVisibility() {
  scheduleLineLabels();
}
function applyStationVisibility() {
  if (!mapReady) return;
  for (let tier = 1; tier <= 4; tier++) {
    const v = state.stationLayer ? 'visible' : 'none';
    map.setLayoutProperty('station-dot-' + tier, 'visibility', v);
    map.setLayoutProperty('station-ring-' + tier, 'visibility', v);
  }
}
function applyAdminVisibility() {
  if (!mapReady) return;
  for (const [level, ids] of Object.entries(ADMIN_LAYERS)) {
    const v = state.adminLevels[level] ? 'visible' : 'none';
    for (const id of ids) map.setLayoutProperty(id, 'visibility', v);
  }
}
function applyProvinceBordersVisibility() {
  if (!mapReady) return;
  map.setLayoutProperty('prov-lines', 'visibility', state.provinceBorders ? 'visible' : 'none');
}
function applyJunctionVisibility() {
  if (!mapReady) return;
  for (const id of ['junction-links', 'junction-nodes-major', 'junction-nodes-minor']) {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', state.junctionLayer ? 'visible' : 'none');
  }
}
function initAdminControls() {
  const counts = {
    province: basemap.provinceLabels.features.length,
    city: basemap.cityLabels.features.length,
    county: basemap.countyLabels.features.length,
  };
  $$('.admin-bar .lvl').forEach(btn => {
    const level = btn.dataset.level;
    btn.title = `${level === 'province' ? '省级' : level === 'city' ? '地级' : '县级'}行政地名（${fmt(counts[level])} 处）`;
    btn.addEventListener('click', () => {
      state.adminLevels[level] = !state.adminLevels[level];
      btn.classList.toggle('on', state.adminLevels[level]);
      btn.setAttribute('aria-pressed', state.adminLevels[level] ? 'true' : 'false');
      applyAdminVisibility();
    });
  });
  const b = $('#toggleProvinceBorders');
  b.addEventListener('click', () => {
    state.provinceBorders = !state.provinceBorders;
    b.classList.toggle('on', state.provinceBorders);
    b.setAttribute('aria-pressed', state.provinceBorders ? 'true' : 'false');
    applyProvinceBordersVisibility();
  });
}

/* ---------------------------------------------------------------- selection */
function clearSelection(silent = false) {
  state.selectedLine = null;
  state.selectedStation = null;
  if (mapReady) {
    map.getSource('selection').setData({ type: 'FeatureCollection', features: [] });
    map.getSource('selectedStation').setData({ type: 'FeatureCollection', features: [] });
  }
  document.body.classList.remove('detail-open');
  $('#detailPanel').classList.remove('open');
  $$('.line-item.selected').forEach(el => el.classList.remove('selected'));
  if (!silent) { /* keep map view */ }
}
function fitLine(line, animate = true) {
  if (!mapReady) return;
  const b = lineBounds(line.id);
  if (!b.isEmpty()) {
    const narrow = isNarrow();
    // A previous station flyTo stores asymmetric padding. Reset it before
    // adding the line-fit padding, otherwise MapLibre sums both and cannot fit.
    map.setPadding({ top: 0, bottom: 0, left: 0, right: 0 });
    map.fitBounds(b, {
      padding: narrow ? { top: 36, bottom: Math.max(300, window.innerHeight * .48), left: 18, right: 18 } : { top: 64, bottom: 64, left: 426, right: 418 },
      duration: animate ? 950 : 0, maxZoom: 8.4,
    });
  }
}
function selectLine(id, opts = {}) {
  const line = lineById.get(Number(id));
  $('#mapTip').hidden = true;
  if (!line) return;
  state.selectedLine = line;
  state.selectedStation = null;
  closeSearch();
  if (mapReady) {
    map.getSource('selection').setData(lineGeoJSON(line.id));
    map.getSource('selectedStation').setData({ type: 'FeatureCollection', features: [] });
  }
  renderLineDetail(line);
  openDetail(lineColor(line));
  document.body.classList.add('detail-open');
  $$('.line-item.selected').forEach(el => el.classList.remove('selected'));
  const listEl = document.querySelector(`.line-item[data-id="${line.id}"]`);
  if (listEl) { listEl.classList.add('selected'); if (opts.scroll !== false) listEl.scrollIntoView({ block: 'nearest' }); }
  if (opts.fit !== false) fitLine(line, true);
  scheduleLineLabels();
}
function detailPadRight() {
  const w = $('#detailPanel')?.getBoundingClientRect().width || 420;
  return Math.round(w + 30);
}
function selectStation(id, opts = {}) {
  const s = stationById.get(Number(id));
  $('#mapTip').hidden = true;
  if (!s) return;
  state.selectedStation = s;
  state.selectedLine = null;
  closeSearch();
  if (mapReady) {
    map.getSource('selectedStation').setData(stationGeoJSON(s));
    map.getSource('selection').setData({ type: 'FeatureCollection', features: [] });
  }
  renderStationDetail(s);
  openDetail(C.accent);
  document.body.classList.add('detail-open');
  $$('.line-item.selected').forEach(el => el.classList.remove('selected'));
  scheduleLineLabels();
  if (opts.fit !== false && mapReady) {
    map.flyTo({
      center: [s.lon, s.lat], zoom: Math.max(10.8, Math.min(map.getZoom(), 12.4)),
      speed: 1.1, curve: 1.35, duration: 1200, padding: isNarrow() ? { bottom: Math.max(280, window.innerHeight * .47), top: 20 } : { left: 426, right: detailPadRight(), top: 20, bottom: 20 },
    });
  }
}
function openDetail(color) {
  const panel = $('#detailPanel');
  panel.style.setProperty('--dc', color);
  $('#detailAccent').style.background = color;
  panel.classList.add('open');
  $('#detailScroll').scrollTop = 0;
}
function closeDetail() {
  clearSelection();
  scheduleLineLabels();
}

/* ---------------------------------------------------------------- detail render */
function renderLineDetail(line) {
  $('#detailKicker').textContent = '线路档案 / LINE';
  $('#detailName').textContent = line.name;
  const m = SPEEDS[line.speed] || SPEEDS[120];
  $('#detailSub').textContent = `${line.type} · 图定列车经行线路`;
  $('#detailTags').innerHTML = `
    <span class="tag speed"><b>${line.speed}</b> km/h</span>
    <span class="tag">${esc(line.type)}</span>
    <span class="tag">${line.tier === 1 ? '国家干线' : line.tier === 2 ? '主要线路' : '客运线路'}</span>
    <span class="tag">${fmt(line.stationCount)} 站</span>`;
  const stationsList = (line.stations || []).filter(s => Number(s.rank) > 0);
  const stationRows = stationsList.length
    ? stationsList.map((s, i) => `<button class="station-row" data-station-id="${s.id}"><span class="ss-index">${String(i + 1).padStart(2, '0')}</span><span class="ss-main"><span class="ss-name">${esc(s.name)}</span><span class="ss-city">${esc(s.city || '')}</span></span><span class="ss-rank">${fmt(s.rank)}<small>列</small></span></button>`).join('')
    : `<div class="station-no-data">这条线路暂无可检索的办客车站。</div>`;
  const note = line.note || '按该线路最高运营速度等级标注；具体区段的运行速度受线路条件、停站与运行图影响，可能低于标注值。';
  $('#detailBody').innerHTML = `
    <div class="detail-rule"></div>
    <div class="detail-stats">
      <div class="detail-stat"><b style="color:${m.color}">${line.speed}</b><span>最高运营 km/h</span></div>
      <div class="detail-stat"><b>${fmt(line.stationCount)}</b><span>关联车站</span></div>
      <div class="detail-stat"><b>${fmt(line.cities || 0)}</b><span>关联城市</span></div>
    </div>
    <div class="detail-note">${esc(note)}</div>
    <div class="detail-section-title"><h3>沿线办客车站</h3><span>${fmt(stationsList.length)} 站 · 按经行顺序</span></div>
    <div class="station-list-scroll">${stationRows}</div>
    <div class="station-list-note">仅列 12306 办理客运的车站；不同列车停站不完全相同，序号为线路经行顺序。</div>
    <div class="detail-section-title"><h3>线路信息</h3><span>LINE FACTS</span></div>
    <div class="detail-meta">
      <div class="meta-row"><span class="m-key">线路类型</span><span class="m-val">${esc(line.type)}</span></div>
      <div class="meta-row"><span class="m-key">速度等级</span><span class="m-val">${line.speed} km/h · ${m.name}</span></div>
      <div class="meta-row"><span class="m-key">关联车站 / 城市</span><span class="m-val">${fmt(line.stationCount)} / ${fmt(line.cities || 0)}</span></div>
      <div class="meta-row"><span class="m-key">线路识别</span><span class="m-val">OpenStreetMap × 12306 图定径路</span></div>
    </div>
    <div class="detail-source">线路几何经拓扑合并与简化；车站与线路的对应关系依据图定列车径路与站场邻近度计算，用于空间参考。速度标注为线路最高运营等级，非全线各区段实测速度。</div>
    <button class="detail-action" data-action="fit-line">在图中聚焦整条线路</button>
    <button class="detail-action ghost" data-action="close-detail">关闭档案</button>`;
  $$('[data-station-id]', $('#detailBody')).forEach(btn => btn.addEventListener('click', () => selectStation(btn.dataset.stationId, { fit: true })));
  const fit = $('[data-action="fit-line"]', $('#detailBody'));
  if (fit) fit.addEventListener('click', () => fitLine(line, true));
  $('[data-action="close-detail"]', $('#detailBody'))?.addEventListener('click', closeDetail);
}
function renderStationDetail(s) {
  $('#detailKicker').textContent = '车站档案 / STATION';
  $('#detailName').textContent = s.name;
  $('#detailSub').textContent = placeText(s) || '国家铁路客运车站';
  const sl = stationLines(s);
  $('#detailTags').innerHTML = `
    <span class="tag speed"><b>${fmt(s.rank)}</b> 列</span>
    <span class="tag">${esc(HUB_NAME[s.tier] || '车站')}</span>
    ${s.tele ? `<span class="tag">电报码 ${esc(s.tele)}</span>` : ''}`;
  const lineRows = sl.length ? sl.slice(0, 7).map(l => {
    const line = lineByName.get(l.name); const col = line ? lineColor(line) : '#888';
    return `<button class="line-chip" data-line-id="${line ? line.id : ''}"><span class="lc-bar" style="--c:${col}"></span><span class="lc-name">${esc(l.name)}</span><span class="lc-speed">${l.speed || ''} km/h</span></button>`;
  }).join('') : `<div class="station-no-data">暂无匹配到在办客运线路。</div>`;
  $('#detailBody').innerHTML = `
    <div class="detail-rule"></div>
    <div class="detail-stats">
      <div class="detail-stat"><b>${fmt(s.rank)}</b><span>图定停靠列车</span></div>
      <div class="detail-stat"><b>${sl.length}</b><span>接驳客运线路</span></div>
      <div class="detail-stat"><b style="font-family:var(--mono);font-size:13px;letter-spacing:.02em">${esc(s.tele || '—')}</b><span>车站电报码</span></div>
    </div>
    <div class="detail-section-title"><h3>接驳客运线路</h3><span>LINES SERVED</span></div>
    <div class="line-chips">${lineRows}</div>
    <div class="detail-section-title"><h3>车站信息</h3><span>STATION FACTS</span></div>
    <div class="detail-meta">
      <div class="meta-row"><span class="m-key">所属城市</span><span class="m-val">${esc(placeText(s) || '—')}</span></div>
      <div class="meta-row"><span class="m-key">拼音 / 简拼</span><span class="m-val">${esc(s.py || '—')}${s.abbr ? ' / ' + esc(s.abbr) : ''}</span></div>
      <div class="meta-row"><span class="m-key">经纬度</span><span class="m-val">${s.lat.toFixed(4)}°N, ${s.lon.toFixed(4)}°E</span></div>
      <div class="meta-row"><span class="m-key">图定频次</span><span class="m-val">${fmt(s.rank)} 列（12306 图定停靠计数）</span></div>
    </div>
    <div class="detail-source">车站表、电报码、图定停靠与线路服务由 12306 公开数据整理；坐标来自 OpenStreetMap / 12306 车站表。车站层级按图定停靠频次相对划分，不等同于铁路车站行政等级。</div>
    <button class="detail-action" data-action="zoom-station">在图中定位该站</button>
    <button class="detail-action ghost" data-action="close-detail">关闭档案</button>`;
  $$('[data-line-id]', $('#detailBody')).forEach(btn => btn.addEventListener('click', () => {
    const id = Number(btn.dataset.lineId); if (Number.isFinite(id) && lineById.has(id)) selectLine(id, { fit: true });
  }));
  $('[data-action="zoom-station"]', $('#detailBody'))?.addEventListener('click', () => {
    if (mapReady) map.flyTo({ center: [s.lon, s.lat], zoom: Math.max(map.getZoom(), 8), duration: 900, padding: isNarrow() ? { bottom: Math.max(280, window.innerHeight * .47) } : { left: 426, right: 416 } });
  });
  $('[data-action="close-detail"]', $('#detailBody'))?.addEventListener('click', closeDetail);
}

/* ---------------------------------------------------------------- inset */
function initInset() {
  const insetStyle = {
    version: 8,
    glyphs: 'glyph://{fontstack}/{range}.pbf',
    sources: {
      land: { type: 'geojson', data: basemap.land },
      provinces: { type: 'geojson', data: basemap.provinces },
    chinaLand: { type: 'geojson', data: basemap.chinaLand },
    nationLandBorders: { type: 'geojson', data: basemap.nationLandBorders },
    provLandLines: { type: 'geojson', data: basemap.provLandLines },
      nation: { type: 'geojson', data: basemap.nation },
      maritime: { type: 'geojson', data: basemap.maritime },
      lakes: { type: 'geojson', data: basemap.lakes },
    riverAreas: { type: 'geojson', data: basemap.riverAreas },
      provLines: { type: 'geojson', data: basemap.provLines },
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#c8dcda' } },
      { id: 'land', type: 'fill', source: 'land', paint: { 'fill-color': '#e9e2d3' } },
      { id: 'china', type: 'fill', source: 'provinces', paint: { 'fill-color': '#f7f1e4' } },
      { id: 'lakes', type: 'fill', source: 'lakes', paint: { 'fill-color': '#b7d3d1' } },
      { id: 'provLines', type: 'line', source: 'provLines', paint: { 'line-color': 'rgba(120,102,80,.38)', 'line-width': .4, 'line-dasharray': [2, 2] } },
      { id: 'nation', type: 'line', source: 'nation', paint: { 'line-color': '#77634e', 'line-width': 1.0 } },
      { id: 'maritime', type: 'line', source: 'maritime', paint: { 'line-color': '#77634e', 'line-width': .85 } },
    ],
  };
  const im = new maplibregl.Map({
    container: 'insetMap', style: insetStyle, interactive: false, attributionControl: false,
    center: [112.3, 13.2], zoom: 3.0, renderWorldCopies: false, dragRotate: false,
  });
  im.on('load', () => {
    im.fitBounds([[105.2, 2.4], [123.9, 23.7]], { padding: 3, duration: 0 });
  });
}

/* ---------------------------------------------------------------- UI build */
function initStats() {
  $('#statLines').textContent = fmt(meta.lines);
  $('#statStations').textContent = fmt(meta.stations);
  $('#statCities').textContent = fmt(meta.cities);
  const alc = $('#aboutLineCount'); if (alc) alc.textContent = fmt(meta.lines);
  const asc = $('#aboutStationCount'); if (asc) asc.textContent = fmt(meta.stations);
  $('#lineCountTab').textContent = String(meta.lines);
  $('#lineCountTab').setAttribute('aria-label', meta.lines + ' 条线路');
}
function setSpeedThreshold(min) {
  visibleSpeeds.clear();
  for (const speed of SPEED_ORDER) {
    if (!min || speed >= min) visibleSpeeds.add(speed);
  }
  applyLineFilters();
}

function syncSpeedFilter() {
  const sel = $('#speedFilter');
  if (!sel) return;
  let value = 'custom';
  if (visibleSpeeds.size === SPEED_ORDER.length) value = 'all';
  else {
    for (const min of [350, 300, 250, 200, 160, 120]) {
      const target = SPEED_ORDER.filter(s => s >= min);
      if (target.length === visibleSpeeds.size && target.every(s => visibleSpeeds.has(s))) { value = String(min); break; }
    }
  }
  sel.value = value;
  const count = $('#speedFilterCount');
  if (count) {
    const shown = lines.reduce((n, l) => n + (visibleSpeeds.has(l.speed) ? 1 : 0), 0);
    count.textContent = `${shown} / ${lines.length}`;
    count.title = `当前显示 ${shown} 条线路`;
  }
}

function initSpeedFilter() {
  const sel = $('#speedFilter');
  if (!sel) return;
  sel.addEventListener('change', () => {
    const v = sel.value;
    setSpeedThreshold(v === 'all' ? 0 : Number(v));
  });
  syncSpeedFilter();
}

function initPanelCollapse() {
  const panel = $('#panel');
  const collapse = $('#panelCollapse');
  const reopen = $('#panelReopen');
  if (!panel || !collapse || !reopen) return;
  function setCollapsed(v) {
    document.body.classList.toggle('panel-collapsed', v);
    collapse.setAttribute('aria-expanded', String(!v));
    reopen.setAttribute('aria-expanded', String(v));
    panel.setAttribute('aria-hidden', String(v));
    if ('inert' in panel) panel.inert = v;
    scheduleLineLabels();
    setTimeout(() => {
      if (mapReady) map.resize();
      scheduleLineLabels();
    }, 420);
  }
  collapse.addEventListener('click', () => { setCollapsed(true); reopen.focus({ preventScroll: true }); });
  reopen.addEventListener('click', () => { setCollapsed(false); collapse.focus({ preventScroll: true }); });
}

function initLegend() {
  $('#speedLegend').innerHTML = SPEED_ORDER.map(speed => `<button class="speed-row" data-speed="${speed}" aria-pressed="true">${optionHTML(speed)}</button>`).join('');
  $$('#speedLegend .speed-row').forEach(btn => btn.addEventListener('click', () => {
    const speed = Number(btn.dataset.speed);
    if (visibleSpeeds.has(speed)) {
      if (visibleSpeeds.size === 1) { toast('至少保留一个速度等级'); return; }
      visibleSpeeds.delete(speed);
    } else visibleSpeeds.add(speed);
    applyLineFilters();
    scheduleLineLabels();
  }));
  const mleg = SPEED_ORDER.map(speed => `<button class="mleg" data-speed="${speed}" title="筛选 ${speed} km/h"><i style="--c:${SPEEDS[speed].color}"></i>${speed}<small>km/h</small></button>`).join('');
  $('#mapLegend').innerHTML = `<span class="legend-title">运营时速</span>${mleg}`;
  $$('#mapLegend .mleg').forEach(btn => btn.addEventListener('click', () => {
    const speed = Number(btn.dataset.speed);
    if (visibleSpeeds.has(speed)) { if (visibleSpeeds.size === 1) return; visibleSpeeds.delete(speed); }
    else visibleSpeeds.add(speed);
    applyLineFilters();
    scheduleLineLabels();
  }));
}
function initToggles() {
  const lineT = $('#toggleLineLabels'), stT = $('#toggleStations');
  lineT.addEventListener('click', () => {
    state.lineLabels = !state.lineLabels;
    lineT.classList.toggle('on', state.lineLabels); lineT.setAttribute('aria-pressed', state.lineLabels);
    applyLabelVisibility();
  });
  stT.addEventListener('click', () => {
    state.stationLayer = !state.stationLayer;
    stT.classList.toggle('on', state.stationLayer); stT.setAttribute('aria-pressed', state.stationLayer);
    applyStationVisibility();
    scheduleLineLabels();
  });
  const junctionT = $('#toggleJunctions');
  if (junctionT) junctionT.addEventListener('click', () => {
    state.junctionLayer = !state.junctionLayer;
    junctionT.classList.toggle('on', state.junctionLayer);
    junctionT.setAttribute('aria-pressed', state.junctionLayer ? 'true' : 'false');
    applyJunctionVisibility();
  });
}
function initFeatured() {
  const names = ['京沪高铁', '京广高铁', '沪昆高铁', '京哈高铁', '京港高铁', '陇海铁路', '京九铁路', '兰新铁路', '青藏铁路', '成昆铁路'];
  const items = names.map(n => lineByName.get(n)).filter(Boolean);
  $('#featuredGrid').innerHTML = items.map(l => `<button class="featured" data-id="${l.id}"><span class="f-dot" style="--c:${lineColor(l)}"></span><span class="f-name">${esc(l.name)}</span><span class="f-speed">${l.speed}</span></button>`).join('');
  $$('#featuredGrid .featured').forEach(b => b.addEventListener('click', () => selectLine(b.dataset.id, { fit: true })));
}
function initLineList() {
  const wrap = $('#lineList');
  const frag = document.createDocumentFragment();
  for (const l of lines) {
    const b = document.createElement('button');
    b.className = 'line-item';
    b.dataset.id = l.id; b.dataset.speed = l.speed; b.dataset.name = l.name; b.dataset.type = l.type;
    const sub = `${l.type} · ${l.stationCount} 站`;
    b.innerHTML = `<span class="li-bar" style="--c:${lineColor(l)}"></span><span class="li-main"><span class="li-name">${esc(l.name)}</span><span class="li-sub">${esc(sub)}</span></span><span class="li-speed">${l.speed}</span>`;
    b.addEventListener('click', () => selectLine(l.id, { fit: true }));
    frag.appendChild(b);
  }
  wrap.appendChild(frag);
  const filter = $('#lineFilter');
  filter.addEventListener('input', () => { state.lineQuery = filter.value.trim().toLowerCase(); renderLineList(); });
  $$('#lineSegmented .seg').forEach(btn => btn.addEventListener('click', () => {
    $$('#lineSegmented .seg').forEach(b => b.classList.remove('active'));
    btn.classList.add('active'); state.lineType = btn.dataset.filter; renderLineList();
  }));
  renderLineList();
}
function renderLineList() {
  if (!$('#lineList')) return;
  let shown = 0;
  $$('#lineList .line-item').forEach(el => {
    const speed = Number(el.dataset.speed);
    const typeOk = state.lineType === 'all' || (state.lineType === 'hsr' ? speed >= 250 : speed < 250);
    const speedOk = visibleSpeeds.has(speed);
    const q = state.lineQuery;
    const queryOk = !q || el.dataset.name.toLowerCase().includes(q) || el.dataset.type.toLowerCase().includes(q);
    const ok = typeOk && queryOk && speedOk;
    el.style.display = ok ? '' : 'none';
    if (ok) shown++;
  });
  let empty = $('#lineList .empty-lines');
  if (!shown) {
    if (!empty) { empty = document.createElement('div'); empty.className = 'empty-lines'; empty.style.cssText = 'padding:26px 4px;font-size:10px;color:var(--ink-3);text-align:center'; empty.textContent = '没有匹配的线路'; $('#lineList').appendChild(empty); }
  } else if (empty) empty.remove();
}
function initHubs() {
  const items = [...stations].sort((a, b) => b.rank - a.rank).slice(0, 28);
  $('#hubList').innerHTML = items.map(s => `<button class="station-card" data-id="${s.id}"><span class="sc-name">${esc(s.name)}</span><span class="sc-city">${esc(placeText(s))}</span></button>`).join('');
  $$('#hubList .station-card').forEach(b => b.addEventListener('click', () => selectStation(b.dataset.id, { fit: true })));
}

/* ---------------------------------------------------------------- tabs & search */
function switchTab(name) {
  state.activeTab = name;
  const tabBody = $('#tabBody');
  if (tabBody) tabBody.scrollTop = 0;
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  $$('.tab').forEach(t => t.setAttribute('aria-selected', t.dataset.tab === name ? 'true' : 'false'));
  $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
}
$$('.tab').forEach(t => t.addEventListener('click', () => switchTab(t.dataset.tab)));
$('#tab-btn-lines').addEventListener('click', () => setTimeout(() => $('#lineFilter').focus(), 60));

const stationSearch = stations.map(s => ({ s, hay: [s.name, s.py, s.abbr, s.tele, s.city, s.province].filter(Boolean).join(' ').toLowerCase() }));
const lineSearch = lines.map(l => ({ l, hay: [l.name, l.type].join(' ').toLowerCase() }));
function scoreMatch(hay, name, q) {
  const n = name.toLowerCase();
  if (n === q) return 100;
  if (n.startsWith(q)) return 78;
  if (n.includes(q)) return 56;
  if (hay.includes(q)) return 36;
  return 0;
}
function searchResults(q) {
  const query = q.trim().toLowerCase();
  if (!query) {
    const hotLines = ['京沪高铁', '京广高铁', '沪昆高铁', '京哈高铁', '青藏铁路'].map(n => lineByName.get(n)).filter(Boolean);
    const hotStations = ['北京南', '上海虹桥', '广州南', '深圳北', '成都东'].map(n => stationByName.get(n)).filter(Boolean);
    return { lines: hotLines.slice(0, 4), stations: hotStations.slice(0, 4), query: '' };
  }
  const ls = lineSearch.map(x => ({ ...x, score: scoreMatch(x.hay, x.l.name, query) })).filter(x => x.score).sort((a, b) => b.score - a.score).slice(0, 5);
  const ss = stationSearch.map(x => ({ ...x, score: scoreMatch(x.hay, x.s.name, query) })).filter(x => x.score).sort((a, b) => b.score - a.score).slice(0, 6);
  return { lines: ls.map(x => x.l), stations: ss.map(x => x.s), query };
}
function closeSearch() {
  $('#searchResults').classList.remove('open');
  $('#searchInput').setAttribute('aria-expanded', 'false');
  state.searchIndex = -1;
}
function renderSearch() {
  const q = $('#searchInput').value;
  const { lines: foundLines, stations: foundStations, query } = searchResults(q);
  const panel = $('#searchResults');
  if (!query) {
    panel.innerHTML = `
      <div class="sr-group-label"><span>快速开始 · 线路</span><span>LINE</span></div>
      ${foundLines.map(l => `<button class="sr-item" data-kind="line" data-id="${l.id}"><span class="bar" style="background:${lineColor(l)}"></span><span class="sr-main"><span class="sr-name">${esc(l.name)}</span><span class="sr-sub">${esc(l.type)} · ${l.stationCount} 站</span></span><span class="sr-speed">${l.speed}</span></button>`).join('')}
      <div class="sr-group-label"><span>枢纽车站</span><span>STATION</span></div>
      ${foundStations.map(s => `<button class="sr-item" data-kind="station" data-id="${s.id}"><span class="bar" style="background:var(--accent)"></span><span class="sr-main"><span class="sr-name">${esc(s.name)}</span><span class="sr-sub">${esc(placeText(s))}</span></span><span class="sr-speed">${fmt(s.rank)} 列</span></button>`).join('')}`;
  } else if (!foundLines.length && !foundStations.length) {
    panel.innerHTML = `<div class="sr-empty">没有找到“${esc(query)}”<br><span style="font-size:9px;color:var(--ink-3)">可试试线路名、车站名、拼音或电报码</span></div>`;
  } else {
    panel.innerHTML = `
      ${foundLines.length ? `<div class="sr-group-label"><span>线路 · ${foundLines.length}</span><span>LINE</span></div>` + foundLines.map(l => `<button class="sr-item" data-kind="line" data-id="${l.id}"><span class="bar" style="background:${lineColor(l)}"></span><span class="sr-main"><span class="sr-name">${esc(l.name)}</span><span class="sr-sub">${esc(l.type)} · ${l.stationCount} 站</span></span><span class="sr-speed">${l.speed}</span></button>`).join('') : ''}
      ${foundStations.length ? `<div class="sr-group-label"><span>车站 · ${foundStations.length}</span><span>STATION</span></div>` + foundStations.map(s => `<button class="sr-item" data-kind="station" data-id="${s.id}"><span class="bar" style="background:var(--accent)"></span><span class="sr-main"><span class="sr-name">${esc(s.name)}</span><span class="sr-sub">${esc(placeText(s))}</span></span><span class="sr-speed">${fmt(s.rank)} 列</span></button>`).join('') : ''}
      <button class="sr-all" data-kind="all">在完整线路目录中查找 →</button>`;
  }
  panel.classList.add('open');
  $('#searchInput').setAttribute('aria-expanded', 'true');
  state.searchIndex = -1;
  $$('.sr-item,.sr-all', panel).forEach(el => el.addEventListener('click', () => {
    if (el.dataset.kind === 'line') selectLine(el.dataset.id, { fit: true });
    else if (el.dataset.kind === 'station') selectStation(el.dataset.id, { fit: true });
    else { switchTab('lines'); closeSearch(); $('#lineFilter').focus(); }
  }));
}
function initSearch() {
  const input = $('#searchInput'), clear = $('#searchClear');
  input.addEventListener('focus', () => { if (!input.value.trim()) renderSearch(); else renderSearch(); });
  input.addEventListener('input', () => {
    clear.classList.toggle('show', !!input.value);
    renderSearch();
  });
  input.addEventListener('keydown', (e) => {
    const items = $$('#searchResults .sr-item,#searchResults .sr-all');
    if (e.key === 'Escape') { closeSearch(); input.blur(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!items.length) return;
      state.searchIndex = (state.searchIndex + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items.forEach((x, i) => x.classList.toggle('active', i === state.searchIndex));
      items[state.searchIndex].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (state.searchIndex >= 0 && items[state.searchIndex]) items[state.searchIndex].click();
    }
  });
  clear.addEventListener('click', () => { input.value = ''; clear.classList.remove('show'); input.focus(); renderSearch(); });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#searchWrap')) closeSearch();
  });
}

/* ---------------------------------------------------------------- interactions */
function stationLayerIds() {
  return state.stationLayer ? [1, 2, 3, 4].flatMap(t => ['station-dot-' + t, 'station-ring-' + t]) : [];
}
const tip = $('#mapTip');
let hoverTimer = null;
map.on('mousemove', (e) => {
  if (!mapReady) return;
  if (hoverTimer) return;
  hoverTimer = setTimeout(() => { hoverTimer = null; }, 32);
  const labelHit = hitLabel(e.point);
  let station = null;
  let line = null;
  if (labelHit) {
    if (labelHit.type === 'station') station = stationById.get(Number(labelHit.id));
    else if (labelHit.type === 'line') line = lineById.get(Number(labelHit.k));
  }
  if (!station && !line && state.stationLayer) {
    const stationHits = map.queryRenderedFeatures(e.point, { layers: ['station-dot-1', 'station-dot-2', 'station-dot-3', 'station-dot-4'] });
    if (stationHits.length) {
      const f = stationHits[0];
      station = stationById.get(Number(f.properties.id)) || stationByName.get(f.properties.name);
    }
  }
  if (!station && !line) {
    const railHits = map.queryRenderedFeatures(e.point, { layers: ['rail-hit'] });
    if (railHits.length) line = lineById.get(Number(railHits[0].properties.k));
  }
  map.getCanvas().style.cursor = station || line ? 'pointer' : '';
  if (station) {
    const ls = stationLines(station);
    tip.style.setProperty('--tc', C.accent);
    tip.innerHTML = `<span class="tip-line"></span><span class="tip-main"><b>${esc(station.name)}<em>${HUB_NAME[station.tier] || ''}</em></b><small>${esc(placeText(station))} · ${ls.length} 条接驳线路</small></span>`;
    tip.hidden = false;
    tip.style.left = Math.min(e.point.x, map.getCanvas().clientWidth - 270) + 'px';
    tip.style.top = Math.min(e.point.y, map.getCanvas().clientHeight - 70) + 'px';
  } else if (line) {
    tip.style.setProperty('--tc', lineColor(line));
    tip.innerHTML = `<span class="tip-line"></span><span class="tip-main"><b>${esc(line.name)}<em>${line.speed} km/h</em></b><small>${esc(line.type)} · ${line.stationCount} 座站</small></span>`;
    tip.hidden = false;
    tip.style.left = Math.min(e.point.x, map.getCanvas().clientWidth - 280) + 'px';
    tip.style.top = Math.min(e.point.y, map.getCanvas().clientHeight - 70) + 'px';
  } else {
    tip.hidden = true;
  }
});
map.on('mouseout', () => { tip.hidden = true; });
map.on('movestart', () => { tip.hidden = true; });
map.on('click', (e) => {
  if (!mapReady) return;
  const labelHit = hitLabel(e.point);
  if (labelHit) {
    if (labelHit.type === 'station') {
      const s = stationById.get(Number(labelHit.id));
      if (s) { selectStation(s.id, { fit: true }); return; }
    } else if (labelHit.type === 'line') {
      const l = lineById.get(Number(labelHit.k));
      if (l) { selectLine(l.id, { fit: true }); return; }
    }
  }
  if (state.stationLayer) {
    const stationHits = map.queryRenderedFeatures(e.point, { layers: ['station-dot-1', 'station-dot-2', 'station-dot-3', 'station-dot-4'] });
    if (stationHits.length) {
      const f = stationHits[0];
      const s = stationById.get(Number(f.properties.id)) || stationByName.get(f.properties.name);
      if (s) { selectStation(s.id, { fit: true }); return; }
    }
  }
  const railHits = map.queryRenderedFeatures(e.point, { layers: ['rail-hit'] });
  if (railHits.length) {
    const l = lineById.get(Number(railHits[0].properties.k));
    if (l) { selectLine(l.id, { fit: true }); return; }
  }
  if (state.selectedLine || state.selectedStation) closeDetail();
});
$('#detailClose').addEventListener('click', closeDetail);
$('#zoomIn').addEventListener('click', () => map.zoomIn({ duration: 300 }));
$('#zoomOut').addEventListener('click', () => map.zoomOut({ duration: 300 }));
$('#resetView').addEventListener('click', () => { closeDetail(); fitOverview(true); });
$('#fullscreenBtn').addEventListener('click', async () => {
  try {
    if (!document.fullscreenElement) { await document.documentElement.requestFullscreen(); toast('已进入全屏'); }
    else { await document.exitFullscreen(); toast('已退出全屏'); }
    setTimeout(() => map.resize(), 200);
  } catch (err) { toast('浏览器未允许全屏'); }
});
function openModal() {
  state.focusReturn = document.activeElement;
  $('#aboutModal').classList.remove('hidden');
  $('#modalClose').focus();
}
function closeModal() {
  $('#aboutModal').classList.add('hidden');
  if (state.focusReturn && state.focusReturn.focus) state.focusReturn.focus();
}
$('#aboutBtn').addEventListener('click', openModal);
$('#aboutBtn2').addEventListener('click', openModal);
$('#modalClose').addEventListener('click', closeModal);
$('#aboutModal').addEventListener('click', (e) => { if (e.target === $('#aboutModal')) closeModal(); });
document.addEventListener('keydown', (e) => {
  if (e.key === '/' && !/INPUT|TEXTAREA/.test(document.activeElement.tagName) && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); $('#searchInput').focus(); }
  if (e.key === 'Escape') {
    if (!$('#aboutModal').classList.contains('hidden')) { closeModal(); return; }
    if (state.selectedLine || state.selectedStation) { closeDetail(); return; }
    closeSearch();
  }
});


/* ---------------------------------------------------------------- SVG label engine */
const SVGNS = 'http://www.w3.org/2000/svg';
const WATER_LABELS = [
  { n: '长江', lon: 104.5, lat: 29.2, r: 22 },
  { n: '黄河', lon: 105.0, lat: 36.2, r: 26 },
  { n: '珠江', lon: 112.7, lat: 23.2, r: 0 },
  { n: '黑龙江', lon: 126.6, lat: 49.6, r: 18 },
  { n: '雅鲁藏布江', lon: 88.6, lat: 29.3, r: 12 },
  { n: '长江', lon: 120.9, lat: 31.9, r: 0 },
  { n: '钱塘江', lon: 120.6, lat: 30.25, r: 0 },
  { n: '黄河', lon: 117.2, lat: 37.2, r: 0 },
  { n: '珠江', lon: 113.3, lat: 22.8, r: 0 },
];
const SANS_FONT = '"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif';
const lineLabelEls = [];
const stationLabelEls = [];
let placedLabelHits = [];
let labelRaf = null;
const labelCtx = document.createElement('canvas').getContext('2d');
const measureCache = new Map();
const LABEL_DARK = { 350:'#8d291e', 300:'#9c431f', 250:'#836315', 200:'#2d6042', 160:'#1c546a', 140:'#34646f', 120:'#4e5c80', 80:'#6d655b' };
const MAJOR_LABEL_SIZES = { 1: [10.4, 13.4], 2: [9.8, 12.4], 3: [9.2, 11.4], 4: [8.8, 10.8] };
const UI_EXCLUDE = ['#panel', '#detailPanel', '.map-top-actions', '#inset', '#mapFooter'];
const MOBILE_OVERVIEW = new Set(['京沪高铁','京广高铁','沪昆高铁','京哈高铁','京港高铁','徐兰高铁','陇海铁路','京九铁路','兰新铁路','青藏铁路','成昆铁路','沪昆铁路','京广铁路']);

function measure(text, fs, weight, mono = false) {
  const key = `${fs.toFixed(2)}|${weight}|${mono ? 1 : 0}|${text}`;
  let v = measureCache.get(key);
  if (v == null) {
    labelCtx.font = `${weight} ${fs}px ${mono ? '"SF Mono","Menlo",monospace' : SANS_FONT}`;
    v = labelCtx.measureText(text).width;
    measureCache.set(key, v);
  }
  return v;
}
function makeLineGroup(f) {
  const g = document.createElementNS(SVGNS, 'g');
  g.setAttribute('class', 'olabel line');
  const name = document.createElementNS(SVGNS, 'text');
  name.setAttribute('class', 'ol-name'); name.setAttribute('text-anchor', 'middle');
  name.textContent = f.properties.n;
  name.style.fill = LABEL_DARK[f.properties.s] || LABEL_DARK[160];
  const speed = document.createElementNS(SVGNS, 'text');
  speed.setAttribute('class', 'ol-speed'); speed.setAttribute('text-anchor', 'middle');
  speed.textContent = `${f.properties.s} km/h`;
  g.append(name, speed);
  g.style.display = 'none';
  $('#lineLabelLayer').appendChild(g);
  lineLabelEls.push({
    f, g, name, speed, k: f.properties.k, tier: f.properties.z,
    speedVal: f.properties.s, rot: Number(f.properties.r) || 0,
    lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], idx: f.properties.i,
  });
}
function labelFontSize(tier, zoom) {
  const [base, cap] = MAJOR_LABEL_SIZES[tier] || [9, 11];
  return Math.min(cap, base + Math.max(0, zoom - TIER_ZOOM[tier]) * .46);
}
function stationFontSize(tier, zoom) {
  const base = { 1: 10.1, 2: 9.5, 3: 9.0, 4: 8.6 }[tier] || 9;
  const cap = { 1: 12.2, 2: 11.2, 3: 10.3, 4: 9.6 }[tier] || 10;
  return Math.min(cap, base + Math.max(0, zoom - STATION_LABEL_ZOOM[tier]) * .22);
}
function makeStationGroup(s) {
  const g = document.createElementNS(SVGNS, 'g');
  g.setAttribute('class', 'olabel station tier-' + s.tier);
  const text = document.createElementNS(SVGNS, 'text');
  text.setAttribute('class', 'st-name'); text.setAttribute('text-anchor', 'start');
  text.textContent = s.name.endsWith('站') ? s.name : s.name + '站';
  g.appendChild(text);
  g.style.display = 'none';
  $('#lineLabelLayer').appendChild(g);
  stationLabelEls.push({ s, g, text, id: s.id, tier: s.tier, lon: s.lon, lat: s.lat, rank: s.rank, selected: false });
}
function initLineLabelOverlay() {
  if (lineLabelEls.length || stationLabelEls.length) return;
  DATA.lineLabels.features.forEach(makeLineGroup);
  stations.forEach(makeStationGroup);
}
function blockRects() {
  const out = [];
  for (const sel of UI_EXCLUDE) {
    for (const el of document.querySelectorAll(sel)) {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 2 && r.height > 2) out.push({ x: r.left - 6, y: r.top - 6, w: r.width + 12, h: r.height + 12 });
    }
  }
  return out;
}
function overlapping(a, b) {
  return !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y);
}
function scheduleLineLabels() {
  if (!mapReady || labelRaf) return;
  labelRaf = requestAnimationFrame(() => { labelRaf = null; drawLineLabels(); });
}
function projectCull(el, bounds) {
  return el.lon >= bounds.getWest() && el.lon <= bounds.getEast() && el.lat >= bounds.getSouth() && el.lat <= bounds.getNorth();
}
function drawWaterLabels() {
  if (!mapReady) return;
  const svg = $('#waterLabelLayer');
  if (!svg) return;
  const width = map.getCanvas().clientWidth, height = map.getCanvas().clientHeight;
  if (svg.getAttribute('width') !== String(width) || svg.getAttribute('height') !== String(height)) {
    svg.setAttribute('width', width); svg.setAttribute('height', height);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  }
  svg.innerHTML = '';
  const z = map.getZoom();
  if (z < 3.05 || z > 11.8) return;
  const bounds = map.getBounds();
  for (const w of WATER_LABELS) {
    if (w.lon < bounds.getWest() - 1 || w.lon > bounds.getEast() + 1 || w.lat < bounds.getSouth() - 1 || w.lat > bounds.getNorth() + 1) continue;
    const p = map.project([w.lon, w.lat]);
    if (p.x < 20 || p.x > width - 20 || p.y < 30 || p.y > height - 26) continue;
    const g = document.createElementNS(SVGNS, 'g');
    g.setAttribute('transform', `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)}) rotate(${w.r})`);
    const t = document.createElementNS(SVGNS, 'text');
    t.setAttribute('x', '0'); t.setAttribute('y', '0');
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('dominant-baseline', 'middle');
    t.setAttribute('class', 'water-label');
    t.textContent = w.n;
    g.appendChild(t); svg.appendChild(g);
  }
}

function drawLineLabels() {
  if (!mapReady) return;
  const svg = $('#lineLabelLayer');
  const width = map.getCanvas().clientWidth, height = map.getCanvas().clientHeight;
  if (svg.getAttribute('width') !== String(width) || svg.getAttribute('height') !== String(height)) {
    svg.setAttribute('width', width); svg.setAttribute('height', height);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  }
  for (const h of placedLabelHits) h.el.g.style.display = 'none';
  placedLabelHits = [];
  const zoom = map.getZoom();
  const blockers = blockRects();
  const bb = map.getBounds();
  const bounds = { getWest: () => bb.getWest() - 1, getEast: () => bb.getEast() + 1, getSouth: () => bb.getSouth() - 1, getNorth: () => bb.getNorth() + 1 };
  const selectedLineId = state.selectedLine ? state.selectedLine.id : null;
  const selectedStationId = state.selectedStation ? state.selectedStation.id : null;
  const narrowOverview = window.innerWidth <= 880 && zoom < 3.25;
  const panelRect = $('#panel')?.getBoundingClientRect();
  const detailRect = $('#detailPanel')?.getBoundingClientRect();
  let visLeft = panelRect ? panelRect.right : 0;
  let visRight = width;
  if (document.body.classList.contains('detail-open') && detailRect) visRight = detailRect.left;
  const vx = (visLeft + visRight) / 2;
  const vy = height * .5;
  const stationCandidates = [];
  const lineCandidates = new Map();

  if (state.lineLabels || selectedLineId != null) {
    for (const el of lineLabelEls) {
      const isSelected = el.k === selectedLineId;
      if (!state.lineLabels && !isSelected) continue;
      if (narrowOverview && !MOBILE_OVERVIEW.has(el.f.properties.n) && !isSelected) continue;
      if (zoom < TIER_ZOOM[el.tier] && !isSelected && !narrowOverview) continue;
      if (!visibleSpeeds.has(el.speedVal) && !isSelected) continue;
      if (!projectCull(el, bounds)) continue;
      const p = map.project([el.lon, el.lat]);
      if (p.x < -40 || p.x > width + 40 || p.y < -30 || p.y > height + 30) continue;
      let group = lineCandidates.get(el.k);
      if (!group) {
        const fs = narrowOverview ? 8.7 : labelFontSize(el.tier, zoom);
        const sfs = Math.max(7.0, fs * .68);
        const nw = measure(el.f.properties.n, fs, 600);
        const sw = measure(`${el.speedVal} km/h`, sfs, 600, true);
        group = {
          type: 'line', k: el.k, tier: el.tier, selected: isSelected, el,
          fs, sfs, w: Math.max(nw, sw) + 9, h: fs + sfs + 4,
          priority: isSelected ? 0 : (zoom < 5.2 ? 10 + el.tier * 2 : 11 + el.tier * 2),
          score: el.f.properties.t, anchors: [],
        };
        lineCandidates.set(el.k, group);
      }
      const rot = Math.abs(el.rot) > 42 ? 0 : el.rot;
      const rad = Math.abs(rot) * Math.PI / 180;
      const bw = group.w * Math.cos(rad) + group.h * Math.sin(rad);
      const bh = group.w * Math.sin(rad) + group.h * Math.cos(rad);
      group.anchors.push({ el, x: p.x, y: p.y, rot, bw, bh, d2: (p.x - vx) ** 2 + (p.y - vy) ** 2 });
    }
  }

  if (state.stationLayer || selectedStationId != null) {
    for (const el of stationLabelEls) {
      const isSelected = el.id === selectedStationId;
      if (!state.stationLayer && !isSelected) continue;
      if (zoom < STATION_LABEL_ZOOM[el.tier] && !isSelected) continue;
      if (!projectCull(el, bounds)) continue;
      const p = map.project([el.lon, el.lat]);
      if (p.x < 10 || p.x > width - 10 || p.y < 10 || p.y > height - 10) continue;
      const fs = stationFontSize(el.tier, zoom) * (isSelected ? 1.08 : 1);
      const tw = measure(el.s.name, fs, el.tier <= 2 ? 500 : 400);
      stationCandidates.push({
        type: 'station', el, fs, tw, h: fs + 3, x: p.x, y: p.y,
        priority: isSelected ? 0 : (zoom < 5.2 ? 20 + el.tier * 2 : 10 + el.tier * 2),
        score: el.rank, selected: isSelected,
      });
    }
  }

  const all = [...lineCandidates.values(), ...stationCandidates];
  all.sort((a, b) => {
    if (a.priority !== b.priority) return a.priority - b.priority;
    if (a.selected !== b.selected) return a.selected ? -1 : 1;
    return b.score - a.score;
  });
  const lineCap = narrowOverview ? 8 : zoom < 4.3 ? 40 : zoom < 6.2 ? 24 : 14;
  let lineCount = 0;
  const placed = [];
  for (const c of all) {
    if (c.type === 'line') {
      if (lineCount >= lineCap && !c.selected) continue;
      c.anchors.sort((a, b) => a.d2 - b.d2);
      let done = false;
      for (const a of c.anchors) {
        const rect = { x: a.x - a.bw / 2 - 3, y: a.y - a.bh / 2 - 3, w: a.bw + 6, h: a.bh + 6 };
        if (blockers.some(r => overlapping(rect, r))) continue;
        if (placed.some(r => overlapping(rect, r))) continue;
        const el = a.el;
        el.g.style.display = '';
        el.g.setAttribute('transform', `translate(${a.x.toFixed(2)} ${a.y.toFixed(2)}) rotate(${a.rot})`);
        el.name.setAttribute('y', (-c.sfs * .32).toFixed(2));
        el.speed.setAttribute('y', (c.fs * .82).toFixed(2));
        el.name.style.fontSize = c.fs.toFixed(2) + 'px';
        el.speed.style.fontSize = c.sfs.toFixed(2) + 'px';
        el.g.classList.toggle('selected', c.selected);
        placed.push(rect);
        placedLabelHits.push({ type: 'line', k: el.k, el, rect });
        lineCount++;
        done = true;
        break;
      }
      if (done) continue;
    } else {
      const offsets = [
        { dx: 8, dy: 0, anchor: 'start' }, { dx: -8, dy: 0, anchor: 'end' },
        { dx: 0, dy: -8, anchor: 'middle' }, { dx: 0, dy: 11, anchor: 'middle' },
      ];
      let chosen = null;
      for (const o of offsets) {
        const tx = c.x + o.dx, ty = c.y + o.dy;
        let bx, by;
        if (o.anchor === 'start') { bx = tx; by = ty - c.h / 2; }
        else if (o.anchor === 'end') { bx = tx - c.tw; by = ty - c.h / 2; }
        else { bx = tx - c.tw / 2; by = o.dy < 0 ? ty - c.h : ty; }
        const rect = { x: bx - 2, y: by - 1, w: c.tw + 4, h: c.h + 2 };
        if (rect.x < 2 || rect.x + rect.w > width - 2 || rect.y < 2 || rect.y + rect.h > height - 2) continue;
        if (blockers.some(r => overlapping(rect, r))) continue;
        if (placed.some(r => overlapping(rect, r))) continue;
        chosen = { o, rect, tx, ty };
        break;
      }
      if (!chosen) continue;
      placed.push(chosen.rect);
      c.el.g.style.display = '';
      c.el.g.setAttribute('transform', `translate(${chosen.tx.toFixed(2)} ${chosen.ty.toFixed(2)})`);
      c.el.text.setAttribute('text-anchor', chosen.o.anchor);
      c.el.text.setAttribute('y', chosen.o.anchor === 'middle' ? (chosen.o.dy < 0 ? '-2' : (c.fs - 1).toFixed(2)) : (c.fs * .34).toFixed(2));
      c.el.text.style.fontSize = c.fs.toFixed(2) + 'px';
      c.el.g.classList.toggle('selected', c.selected);
      placedLabelHits.push({ type: 'station', id: c.el.id, el: c.el, rect: chosen.rect });
    }
  }
  drawWaterLabels();
}
function hitLabel(point) {
  for (const r of placedLabelHits) {
    if (point.x >= r.rect.x && point.x <= r.rect.x + r.rect.w && point.y >= r.rect.y && point.y <= r.rect.y + r.rect.h) return r;
  }
  return null;
}
map.on('move', scheduleLineLabels);
map.on('resize', scheduleLineLabels);
map.on('load', scheduleLineLabels);
window.addEventListener('resize', scheduleLineLabels);

/* ---------------------------------------------------------------- init */
function init() {
  initStats(); initLineLabelOverlay(); initLegend(); initSpeedFilter(); initPanelCollapse(); initToggles(); initAdminControls(); initFeatured(); initLineList(); initHubs(); initSearch();
  // allow clicking anywhere in the legend to close detail? no.
}
init();
})();
