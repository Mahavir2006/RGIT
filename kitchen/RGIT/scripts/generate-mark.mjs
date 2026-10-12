// Generates the Sentinel Aperture wordmark contours into src/assets/monogram-shape.json.
// Output keeps the original D monogram contract: an array of [outer, ...holes] polygons
// that scripts/build.mjs feeds straight into ExtrudeGeometry.
//
// The silhouette is three concentric partial rings plus a core disc: a sonar signature that
// also stands for several source channels resolving into one incident. Every contour is
// built from analytic arcs and circles, so no boolean surgery is needed and the result can
// never self-intersect. The silhouette is authored square so it fills the same bounding-box
// contract the original AT_logo geometry used.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const round = value => Math.round(value * 1e4) / 1e4;
const rad = degrees => (degrees * Math.PI) / 180;

// Partial annulus: outer arc out, inner arc back. The trailing angle produces the single
// straight closing edge that keeps the contour simple.
function arcRing(outerR, innerR, startDeg, sweepDeg, steps) {
  const start = rad(startDeg), sweep = rad(sweepDeg);
  const outer = [], inner = [];
  for (let step = 0; step <= steps; step++) {
    const angle = start + sweep * (step / steps);
    outer.push([Math.cos(angle) * outerR, Math.sin(angle) * outerR]);
    inner.push([Math.cos(angle) * innerR, Math.sin(angle) * innerR]);
  }
  return [...outer, ...inner.reverse()];
}

function disc(radius, steps) {
  const points = [];
  for (let step = 0; step < steps; step++) {
    const angle = rad(step / steps * 360);
    points.push([Math.cos(angle) * radius, Math.sin(angle) * radius]);
  }
  return points;
}

const round3 = points => points.map(([x, y]) => [round(x), round(y)]);

// Outer sweep: 300 degrees opening to the north-east. Mid ring: 230 degrees opening to the
// south-west, so the two gaps read as counter-rotating passes over the core.
const polygons = [
  [round3(arcRing(2.6, 1.86, -58, 300, 180))],
  [round3(arcRing(1.52, 0.99, 112, 230, 140))],
  [round3(disc(0.62, 72))]
];

const out = path.join(root, 'src/assets/monogram-shape.json');
await fs.writeFile(out, JSON.stringify(polygons));
const xs = polygons.flat(2).map(point => point[0]);
const ys = polygons.flat(2).map(point => point[1]);
console.log(`Sentinel Aperture mark written to ${path.relative(root, out)}: ${polygons.length} contours, bbox ${(Math.max(...xs) - Math.min(...xs)).toFixed(3)} x ${(Math.max(...ys) - Math.min(...ys)).toFixed(3)}, ${polygons.flat(2).length} vertices`);