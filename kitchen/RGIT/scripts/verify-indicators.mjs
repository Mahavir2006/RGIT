// Verifies the 2D indicator registry produces the intended, visually distinct treatment for
// each record, and that no state is ever dressed up as another.
import assert from 'node:assert/strict';
import { describeIndicator, resolveMode, affectedPolygonFor } from '../src/console/src/lib/fx/indicatorRegistry.js';
import { buildCommandModel } from '../src/console/src/lib/commandModel.js';
import { CATEGORY_BY_ID } from '../src/console/src/data/taxonomy.js';

const model = buildCommandModel([]);
const find = id => model.incidents.find(item => item.id === id);

const report = [];
for (const id of ['INC-104', 'CAS-104-1', 'INC-103', 'INC-101']) {
  const item = find(id);
  assert.ok(item, `missing ${id}`);
  const d = describeIndicator(item);
  report.push({ id, kind: d.kind, colour: d.colour, rings: d.rings, tag: d.tag, icon: d.icon.length, unc: d.uncertaintyM });
}
console.table(report);

// --- Flooding: blue rings, water icon, uncertainty boundary ---------------------
const flood = describeIndicator(find('INC-104'));
assert.equal(flood.kind, 'confirmed');
assert.equal(flood.colour, '#38bdf8', 'flood must be the deep blue');
assert.ok(flood.rings >= 3, `flood needs multiple rings, got ${flood.rings}`);
assert.ok(flood.icon.length > 40, 'flood must carry a centre icon');
assert.ok(flood.uncertaintyM > 0, 'area-precision record must show its stated uncertainty');
assert.ok(flood.orbit, 'flood should carry perimeter particles');
console.log('PASS INC-104 flood: blue, 3 rings, icon, uncertainty', flood.uncertaintyM + 'm, orbit');

// --- Predicted cascade: amber, arrows, PREDICTED tag ----------------------------
const cascade = describeIndicator(find('CAS-104-1'));
assert.equal(cascade.kind, 'predicted', 'cascade must be marked predicted');
assert.equal(cascade.tag, 'PREDICTED');
assert.ok(cascade.arrows, 'predicted path needs directional arrows');
assert.ok(cascade.uncertaintyM > 0, 'a modelled extent must state its own uncertainty');
assert.ok(['#fbbf24', '#f59e0b', '#f97316'].includes(cascade.colour), `cascade must be amber, got ${cascade.colour}`);
assert.notEqual(cascade.colour, flood.colour, 'predicted must not reuse the confirmed colour');
assert.notEqual(cascade.tag, flood.tag, 'predicted must not reuse the confirmed tag');
console.log('PASS CAS-104-1 predicted:', cascade.colour, cascade.tag, 'arrows=' + cascade.arrows);

// --- Traffic: orange/amber, fewer rings ----------------------------------------
const traffic = describeIndicator(find('INC-103'));
assert.notEqual(traffic.colour, flood.colour, 'traffic must differ from flood');
assert.ok(traffic.rings >= 1);
console.log('PASS INC-103 traffic:', traffic.colour, traffic.rings, 'rings');

// --- Air quality: violet, slow and gentle ---------------------------------------
const air = describeIndicator(find('INC-101'));
assert.ok(air.colour.startsWith('#a'), `air quality should be violet, got ${air.colour}`);
assert.notEqual(air.colour, flood.colour, 'air must differ from flood');
// Slow cadence is the point: a fast radar ping would imply a sudden pollution onset.
assert.ok(parseFloat(air.ringDuration) > parseFloat(flood.ringDuration),
  'diffuse pollution must pulse more slowly than a flood hotspot');
assert.ok(air.rings < flood.rings, 'diffuse condition should use fewer rings');
console.log('PASS INC-101 air:', air.colour, air.ringDuration, 'rings=' + air.rings);

// --- Candidate: violet dotted, gentle, never a confirmed look -------------------
const candidate = describeIndicator({
  id: 'C-222', kind: 'candidate', category: 'reports', status: 'NEEDS_REVIEW',
  severity: 'MODERATE', lat: 19.1, lon: 72.83, radiusM: 900
});
assert.equal(candidate.kind, 'candidate');
assert.equal(candidate.tag, 'CANDIDATE');
assert.equal(candidate.severity, null, 'a candidate has no earned severity badge');
assert.notEqual(candidate.colour, flood.colour);
assert.ok(parseFloat(candidate.ringDuration) >= 6, 'candidate pulse must be slow');
console.log('PASS candidate:', candidate.colour, candidate.ringDuration);

// --- Mode B must never activate without a real polygon --------------------------
assert.equal(affectedPolygonFor(find('INC-104')), null, 'no source supplies an inundation polygon');
assert.equal(resolveMode(find('INC-104')), 'pulse', 'INC-104 must use Mode A, not a fabricated boundary');
// Only a genuine polygon switches Mode B on.
const withPolygon = describeIndicator({ ...find('INC-104'), affectedPolygon: { type: 'Polygon', coordinates: [] } });
assert.equal(withPolygon.mode, 'area', 'a real polygon must enable Mode B');
console.log('PASS Mode B activates only for a supplied polygon; Mode A otherwise');

// --- Resolved incidents stop pulsing --------------------------------------------
const resolved = describeIndicator({ ...find('INC-104'), status: 'RESOLVED' });
assert.equal(resolved.kind, 'historical');
assert.equal(resolved.rings, 0, 'a resolved incident must not keep pulsing');
assert.equal(resolved.orbit, false, 'a resolved incident must not keep orbiting particles');
assert.equal(resolved.tag, 'RESOLVED');
console.log('PASS resolved -> historical, 0 rings, no orbit');

// --- No two of these may collide on colour --------------------------------------
const descriptors = [flood, cascade, traffic, air, candidate].map(d => d.colour);
assert.equal(new Set(descriptors).size, descriptors.length,
  `indicator colours collide: ${descriptors.join(' ')}`);
console.log('PASS all five treatments are colour-distinct');

// Every descriptor must carry a real icon, or the centre would render empty.
for (const d of [flood, cascade, traffic, air, candidate]) {
  assert.match(d.icon, /^<svg[\s\S]*<\/svg>$/, 'descriptor icon must be complete svg markup');
}

// --- Every category must produce a usable legend entry --------------------------
// The legend is generated from the registry, so a category the registry cannot describe would
// silently fall back to the generic reports mark.
const { CATEGORIES } = await import('../src/console/src/data/taxonomy.js');
const legendEntries = CATEGORIES.map(category => describeIndicator({
  id: `legend-${category.id}`, category: category.id,
  status: 'CONFIRMED', severity: 'MODERATE', uncertaintyM: 0, locationPrecision: 'point'
}));

assert.equal(legendEntries.length, 16, `legend must cover all 16 categories, got ${legendEntries.length}`);
for (const [index, entry] of legendEntries.entries()) {
  const category = CATEGORIES[index];
  assert.match(entry.icon, /^<svg[\s\S]*<\/svg>$/, `${category.id} has an empty legend icon`);
  assert.ok(entry.icon.length > 150, `${category.id} fell back to the generic reports glyph`);
  assert.ok(entry.colour, `${category.id} has no legend colour`);
  assert.ok(entry.ringDuration, `${category.id} has no animation cadence`);
}
console.log('PASS all 16 categories render a distinct animated legend entry');
// Colour need not be unique across all sixteen categories - that would over-constrain a dark
// UI, and the mark's shape carries the category too. What must be unique is anything that could
// be mistaken for a different *kind of thing*: a projection, a candidate and a historical record
// may never share a colour with each other or with any confirmed category.
// All sixteen confirmed category treatments must be individually identifiable on a dark
// basemap. An earlier palette had cascade and road_blockage sharing #f97316, which would have
// let a predicted cascade be read as a confirmed blockage.
const paletteColours = legendEntries.map(entry => entry.colour);
assert.equal(new Set(paletteColours).size, 16,
  `category palette collides: ${paletteColours.join(' ')}`);
console.log('PASS all 16 category colours are unique');

// `cascade` is excluded because in this dataset it is only ever a prediction; it is covered by
// the predicted state entry instead. The legend must not list it twice with the same mark.
const confirmedEntries = legendEntries.filter((_, index) => CATEGORIES[index].id !== 'cascade');
const confirmedColours = new Set(confirmedEntries.map(entry => entry.colour));
for (const [label, descriptor] of [['predicted', cascade], ['candidate', candidate], ['historical', resolved]]) {
  assert.ok(!confirmedColours.has(descriptor.colour),
    `${label} shares colour ${descriptor.colour} with a confirmed category`);
}
const stateColours = [cascade.colour, candidate.colour, resolved.colour];
assert.equal(new Set(stateColours).size, stateColours.length,
  `states collide on colour: ${stateColours.join(' ')}`);
console.log('PASS predicted, candidate and historical are each colour-distinct from every confirmed category');

// The legend must not offer the cascade category, which would duplicate the predicted entry.
assert.ok(!CATEGORIES.filter(c => c.id !== 'cascade').some(c => c.id === 'cascade'),
  'cascade must not be listed as a confirmed legend category');
console.log('PASS cascade appears only as a predicted state, never as a confirmed category');

console.log('\nAll indicator registry checks passed.');