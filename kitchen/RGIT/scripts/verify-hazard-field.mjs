// Geometry validation for the thematic hazard field.
import assert from 'node:assert/strict';
import { buildThematicField, themeForCategory } from '../src/console/src/lib/hazardField.js';
import { CATEGORIES } from '../src/console/src/data/taxonomy.js';

const base = { lat: 19.1197, lon: 72.8464, radiusM: 900, assets: [] };

// One representative incident per category, so every theme path is exercised.
const items = CATEGORIES.map((category, index) => ({
  ...base,
  id: `T-${String(index).padStart(2, '0')}`,
  category: category.id,
  // Nudge each incident so an axis-alignment bug cannot hide behind overlapping centres.
  lat: base.lat + index * 0.002,
  lon: base.lon - index * 0.002,
  assets: [{ asset_id: 'A-1', type: 'DRAIN', lat: base.lat, lon: base.lon },
    { asset_id: 'A-2', type: 'GAUGE', lat: base.lat, lon: base.lon },
    { asset_id: 'A-3', type: 'PUMP', lat: base.lat, lon: base.lon }]
}));

// A predicted cascade must not be given a hazard area.
items.push({ ...base, id: 'T-PRED', category: 'cascade', isPredicted: true });

const field = buildThematicField(items);
assert.ok(field.features.length > 0, 'no features generated');

let polygons = 0, lines = 0, points = 0, chains = 0;
const themes = new Set();
const coordRange = { minLat: Infinity, maxLat: -Infinity, minLon: Infinity, maxLon: -Infinity };

function checkCoord(coord) {
  assert.ok(Number.isFinite(coord[0]) && Number.isFinite(coord[1]), `non-finite coordinate ${coord}`);
  coordRange.minLat = Math.min(coordRange.minLat, coord[1]);
  coordRange.maxLat = Math.max(coordRange.maxLat, coord[1]);
  coordRange.minLon = Math.min(coordRange.minLon, coord[0]);
  coordRange.maxLon = Math.max(coordRange.maxLon, coord[0]);
}

for (const feature of field.features) {
  themes.add(feature.properties.theme);
  assert.ok(typeof feature.properties.theme === 'string', 'feature missing theme');
  const geometry = feature.geometry;

  if (geometry.type === 'Polygon') {
    polygons++;
    assert.equal(geometry.coordinates.length, 1, 'expected a single ring');
    const ringCoords = geometry.coordinates[0];
    assert.ok(ringCoords.length >= 4, `ring too short: ${ringCoords.length}`);
    // GeoJSON requires the first and last position to be identical.
    assert.deepEqual(ringCoords[0], ringCoords.at(-1), 'polygon ring is not closed');
    ringCoords.forEach(checkCoord);
  } else if (geometry.type === 'LineString') {
    lines++;
    assert.ok(geometry.coordinates.length >= 2, 'line needs two positions');
    geometry.coordinates.forEach(checkCoord);
  } else if (geometry.type === 'Point') {
    points++;
    checkCoord(geometry.coordinates);
  } else {
    throw new Error(`unexpected geometry ${geometry.type}`);
  }
}

// Everything must sit in the Mumbai operating area, not off in the ocean or at the poles.
assert.ok(coordRange.minLat > 18.9 && coordRange.maxLat < 19.3, `latitude escaped: ${coordRange.minLat}..${coordRange.maxLat}`);
assert.ok(coordRange.minLon > 72.7 && coordRange.maxLon < 72.95, `longitude escaped: ${coordRange.minLon}..${coordRange.maxLon}`);

console.log('features:', field.features.length, '| polygons:', polygons, 'lines:', lines, 'points:', points);
console.log('themes:', [...themes].sort().join(', '));

// Every category must map to a theme, and the cascade must produce a chain not an area.
for (const category of CATEGORIES) {
  assert.ok(themeForCategory(category.id), `${category.id} has no theme`);
}
const predicted = field.features.filter(feature => feature.properties.incident === 'T-PRED');
assert.ok(predicted.length >= 4, `cascade produced ${predicted.length} chain features`);
// The critical invariant: nothing for the predicted cascade may be a filled area.
assert.ok(predicted.every(feature => feature.properties.theme.startsWith('chain')),
  'a predicted cascade was drawn as a hazard area');
assert.ok(predicted.every(feature => feature.geometry.type !== 'Polygon'),
  'a predicted cascade produced a filled polygon');
console.log('PASS predicted cascade is a chain only:', [...new Set(predicted.map(f => f.properties.theme))].join(', '));

// Every feature must be traceable to the incident that produced it.
for (const feature of field.features) {
  assert.ok(feature.properties.incident, `feature with theme ${feature.properties.theme} has no incident tag`);
}

// Flooding must actually produce depth-varying water ribbons.
const water = field.features.filter(feature => feature.properties.theme === 'water');
// One flooding incident requests seven carriageway ribbons.
assert.ok(water.length >= 7, `flooding produced only ${water.length} water features`);
assert.ok(water.every(feature => feature.geometry.type === 'Polygon'), 'water must be drawn as area, not a point');
assert.ok(water.some(feature => feature.properties.detail === 0) && water.some(feature => feature.properties.detail === 1),
  'water needs both coarse and detail passes for zoom-dependent resolution');
const depths = water.map(feature => feature.properties.depth);
assert.ok(Math.max(...depths) > Math.min(...depths), 'water depth is constant, so no depth shading is possible');
assert.ok(depths.every(depth => depth >= 0 && depth <= 1), 'water depth out of range');
console.log('PASS water ribbons:', water.length, 'depth range', Math.min(...depths).toFixed(2), '-', Math.max(...depths).toFixed(2));

// Soft fields must carry a spread so they can be sized in the paint spec.
for (const theme of ['heat', 'haze', 'crowd', 'rain', 'outage']) {
  const cells = field.features.filter(feature => feature.properties.theme === theme);
  assert.ok(cells.length > 0, `theme ${theme} produced no cells`);
  assert.ok(cells.every(cell => Number.isFinite(cell.properties.spreadM)), `${theme} cell missing spreadM`);
}

// A silent sensor is a point at the sensor, never an area.
const dead = field.features.filter(feature => feature.properties.theme === 'dead-sensor');
assert.ok(dead.every(feature => feature.geometry.type === 'Point'), 'a dead sensor was drawn as an area');

// Determinism: the same input must produce byte-identical output, or replay is untrustworthy.
const again = buildThematicField(items);
assert.equal(JSON.stringify(again), JSON.stringify(field), 'hazard field is not deterministic');
console.log('PASS deterministic across rebuilds');

// Every incident must have both a coarse band and a detail band. An earlier version split them
// at random, so some seeds produced an incident with no coarse geometry - invisible until the
// operator zoomed right in - which defeats the purpose of zooming.
const single = { ...base, id: 'SWEEP', category: 'flooding' };
const incomplete = [];
for (let seed = 0; seed < 300; seed++) {
  const sweep = buildThematicField([{ ...single, id: `S${seed}` }]);
  const bands = sweep.features.filter(feature => feature.properties.theme === 'water').map(feature => feature.properties.detail);
  if (!bands.includes(0) || !bands.includes(1)) incomplete.push(`S${seed}`);
}
assert.equal(incomplete.length, 0, `seeds with a missing coarse or detail band: ${incomplete.slice(0, 5).join(', ')}`);
console.log('PASS every seed has both a coarse and a detail band (300 seeds)');

console.log('\nAll hazard-field geometry checks passed.');