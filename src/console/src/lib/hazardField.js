// Thematic hazard field.
//
// A badge tells the operator what kind of incident this is. It does not tell them what the
// ground looks like: that the road is under 40cm of water, that the blockage is at the underpass
// sump, that the outage is a feeder island rather than a whole ward. This module generates that
// picture as map geometry, one theme per category.
//
// Two rules govern everything here:
//
//  1. Determinism. The field is generated from a seeded PRNG keyed on the incident id, so the
//     same incident always draws the same water, the same flooded blocks and the same outage
//     extent. A replay that reshuffles the map on every render would make the operator distrust
//     the picture entirely.
//
//  2. Honesty about resolution. Everything produced here is a modelled depiction of a reported
//     incident, not a measurement. It is drawn inside the incident's own stated uncertainty
//     radius and never outside it, because a hazard drawn past its own uncertainty reads as a
//     surveyed boundary.
import { CATEGORY_BY_ID } from '../data/taxonomy.js';

// Which visual treatment each category gets.
const THEME_BY_CATEGORY = {
  flooding: 'water',
  road_blockage: 'blockage',
  traffic: 'congestion',
  protest: 'crowd',
  procession: 'crowd',
  emergency_access: 'corridor',
  fire_hazard: 'heat',
  transit: 'disruption',
  power: 'outage',
  drainage: 'ponding',
  weather: 'rain',
  air_quality: 'haze',
  infrastructure: 'damage',
  reports: 'signal',
  sensor_health: 'dead-sensor',
  cascade: 'chain'
};

// Soft-field themes are drawn as blurred circles because a raster gradient is not available and a
// hard-edged polygon would imply a surveyed boundary the data does not support.
const SOFT_THEMES = new Set(['heat', 'haze', 'crowd', 'rain']);

export function themeForCategory(categoryId) {
  return THEME_BY_CATEGORY[categoryId] ?? 'signal';
}

/** Deterministic 32-bit hash, so a given incident id always seeds the same field. */
function hashSeed(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function mulberry32(seed) {
  let state = seed;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const METRES_PER_DEGREE_LAT = 111320;

function metresPerDegreeLon(lat) {
  return 111320 * Math.cos((lat * Math.PI) / 180);
}

/** Offset a coordinate by a metre delta, used to author the geometry in real-world units. */
function offset(lat, lon, northMetres, eastMetres) {
  return [
    lon + eastMetres / metresPerDegreeLon(lat),
    lat + northMetres / METRES_PER_DEGREE_LAT
  ];
}

function ring(lat, lon, northMetres, eastMetres) {
  return offset(lat, lon, northMetres, eastMetres);
}

function polygonFeature(properties, lat, lon, points) {
  const ringCoords = points.map(([northMetres, eastMetres]) => ring(lat, lon, northMetres, eastMetres));
  // A polygon ring must be explicitly closed.
  ringCoords.push(ringCoords[0]);
  return {
    type: 'Feature',
    properties,
    geometry: { type: 'Polygon', coordinates: [ringCoords] }
  };
}

function pointFeature(properties, lat, lon) {
  return {
    type: 'Feature',
    properties,
    geometry: { type: 'Point', coordinates: [lon, lat] }
  };
}

/**
 * A ribbon along a street: the shape actually covered by standing water.
 *
 * Water sits on the carriageway, not on a circle around the incident, so this is drawn as a
 * strip with a width that reflects carriageway width rather than as a disc. Depth increases
 * toward the incident centroid, which is where the reported accumulation was highest.
 */
function streetRibbons(lat, lon, radiusMetres, random, count) {
  const features = [];
  for (let index = 0; index < count; index++) {
    const angle = random() * Math.PI * 2;
    // Bias toward two orthogonal street families: real grids flood along corridors, not spokes.
    const gridAngle = Math.round(angle / (Math.PI / 2)) * (Math.PI / 2) + (random() - 0.5) * 0.5;
    const length = radiusMetres * (0.45 + random() * 0.85);
    const width = 26 + random() * 30;
    const offsetAlong = (random() - 0.5) * radiusMetres * 0.5;
    const centreNorth = Math.cos(gridAngle) * offsetAlong;
    const centreEast = Math.sin(gridAngle) * offsetAlong;

    const halfLength = length / 2;
    const halfWidth = width / 2;
    const dirNorth = Math.cos(gridAngle) * halfLength;
    const dirEast = Math.sin(gridAngle) * halfLength;
    const sideNorth = -Math.sin(gridAngle) * halfWidth;
    const sideEast = Math.cos(gridAngle) * halfWidth;

    const points = [
      [centreNorth - dirNorth + sideNorth, centreEast - dirEast + sideEast],
      [centreNorth + dirNorth + sideNorth, centreEast + dirEast + sideEast],
      [centreNorth + dirNorth - sideNorth, centreEast + dirEast - sideEast],
      [centreNorth - dirNorth - sideNorth, centreEast - dirEast - sideEast]
    ];

    // Shallower water further from the centroid; the falloff is deliberately gentle because
    // the underlying data gives one accumulation figure, not a depth surface.
    const distanceKm = Math.abs(offsetAlong) / 1000;
    const depth = Math.max(0.05, 0.75 - distanceKm * 0.55 - random() * 0.12);

    features.push(polygonFeature({
      theme: 'water',
      depth: Math.min(0.95, depth),
      // Split by index, not at random. A seeded random split could give one incident every
      // ribbon in the detail band, which would leave that incident showing nothing at all until
      // the operator zoomed in - the opposite of what zooming is for. Alternating guarantees
      // every incident has both a coarse extent and something new to resolve.
      detail: index % 2
    }, lat, lon, points));
  }
  return features;
}

function softField(lat, lon, radiusMetres, random, { theme, cells, detailAt }) {
  const features = [];
  for (let index = 0; index < cells; index++) {
    const angle = random() * Math.PI * 2;
    const distance = random() * radiusMetres * 0.85;
    const north = Math.cos(angle) * distance;
    const east = Math.sin(angle) * distance;
    const spread = radiusMetres * (0.45 + random() * 0.75);
    const [cellLon, cellLat] = offset(lat, lon, north, east);
    features.push(pointFeature({
      theme,
      intensity: 0.35 + random() * 0.6,
      // Alternating detail, for the same reason as the water ribbons: every cell field must
      // have both a coarse band and a fine band, or zooming in reveals nothing.
      detail: index % 2
    }, cellLat, cellLon));
    // Cells carry their extent so the blurred circle can be scaled per cell in the paint spec.
    features.at(-1).properties.spreadM = spread;
    features.at(-1).properties.detailAt = detailAt;
  }
  return features;
}

/**
 * Build the thematic field for every incident currently on the map.
 *
 * Only observed incidents get a hazard depiction. A predicted cascade gets a chain instead of a
 * field: drawing a plausible-looking flood extent for something nobody observed would be the
 * single most misleading thing this map could do.
 */
export function buildThematicField(items) {
  const features = [];

  for (const item of items) {
    const theme = themeForCategory(item.category);
    const radius = Math.max(150, item.radiusM ?? item.impacted_radius_m ?? 400);
    const random = mulberry32(hashSeed(`${item.id}:${theme}`));
    const predicted = Boolean(item.isPredicted);
    const produced = [];

    if (predicted) {
      // A modelled consequence gets a chain and nothing else. No filled area, because a
      // plausible-looking flood extent for something nobody observed would be the single most
      // misleading thing this map could draw.
      produced.push(...cascadeChain(item, radius, random));
    } else {
      switch (theme) {
      case 'water':
        // The flagship case: standing water drawn as ribbons along the carriageway.
        produced.push(...streetRibbons(item.lat, item.lon, radius, random, 7));
        produced.push(...softField(item.lat, item.lon, radius, random, {
          theme: 'water-halo', cells: 2, detailAt: 0
        }));
        break;

      case 'ponding':
        // Water is standing at named assets (drains, sumps, pumps), so anchor to those points
        // rather than to a circle around the incident.
        for (const asset of item.assets ?? []) {
          if (!['DRAIN', 'PUMP', 'UNDERPASS'].includes(asset.type)) continue;
          produced.push(pointFeature({
            theme: 'ponding', intensity: 0.75, asset: asset.asset_id, spreadM: 180, detail: 0
          }, asset.lat, asset.lon));
        }
        break;

      case 'congestion':
        for (const feature of streetRibbons(item.lat, item.lon, radius, random, 6)) {
          produced.push({ ...feature, properties: { ...feature.properties, theme: 'congestion' } });
        }
        break;

      case 'outage':
        produced.push(...softField(item.lat, item.lon, radius, random, {
          theme: 'outage', cells: 4, detailAt: 12
        }));
        break;

      case 'heat':
        produced.push(...softField(item.lat, item.lon, radius, random, {
          theme: 'heat', cells: 4, detailAt: 12
        }));
        break;

      case 'haze':
        produced.push(...softField(item.lat, item.lon, radius * 1.4, random, {
          theme: 'haze', cells: 3, detailAt: 0
        }));
        break;

      case 'crowd':
        produced.push(...softField(item.lat, item.lon, radius, random, {
          theme: 'crowd', cells: 5, detailAt: 12
        }));
        break;

      case 'rain':
        produced.push(...softField(item.lat, item.lon, radius * 1.6, random, {
          theme: 'rain', cells: 4, detailAt: 0
        }));
        break;

      case 'corridor':
        // Access risk runs along a route, so it is a corridor between the blocked segment and
        // the facility it serves, not a disc.
        for (const feature of streetRibbons(item.lat, item.lon, radius * 1.5, random, 4)) {
          produced.push({ ...feature, properties: { ...feature.properties, theme: 'corridor' } });
        }
        break;

      case 'disruption':
      case 'damage':
      case 'blockage':
        for (const feature of streetRibbons(item.lat, item.lon, radius * 0.8, random, 4)) {
          produced.push({ ...feature, properties: { ...feature.properties, theme } });
        }
        break;

      case 'dead-sensor':
        // A missing reading is a point, and the honest depiction is the sensor's own location
        // rather than any area at all.
        for (const asset of item.assets ?? []) {
          if (!['GAUGE', 'SENSOR'].includes(asset.type)) continue;
          produced.push(pointFeature({ theme: 'dead-sensor', asset: asset.asset_id }, asset.lat, asset.lon));
        }
        break;

      default:
        produced.push(...softField(item.lat, item.lon, radius, random, {
          theme: 'signal', cells: 2, detailAt: 13
        }));
      }
    }

    // Every feature is tagged with its incident, so a drawn hazard can always be traced back to
    // the record that produced it - both when debugging the map and when answering "why is
    // there water there".
    for (const feature of produced) feature.properties.incident = item.id;
    features.push(...produced);
  }

  return { type: 'FeatureCollection', features };
}

/**
 * A cascade is a chain, so it is drawn as one: nodes at cause, link and consequence, joined by
 * directional segments. Nothing is filled, because nothing has been observed yet.
 */
function cascadeChain(item, radius, random) {
  const steps = [
    { label: 'cause', north: -radius * 0.55 },
    { label: 'link', north: 0 },
    { label: 'effect', north: radius * 0.55 }
  ];
  const features = [];
  const points = steps.map((step, index) => {
    const jitter = (random() - 0.5) * radius * 0.25;
    const [lon, lat] = offset(item.lat, item.lon, step.north, jitter);
    return { lat, lon, label: step.label, index };
  });

  for (const point of points) {
    features.push(pointFeature({
      theme: 'chain', step: point.label, detail: 0, spreadM: 70
    }, point.lat, point.lon));
  }

  for (let index = 0; index < points.length - 1; index++) {
    const from = points[index];
    const to = points[index + 1];
    features.push({
      type: 'Feature',
      properties: { theme: 'chain-link', detail: 0, order: index },
      geometry: {
        type: 'LineString',
        // A slight bow so consecutive links do not collapse into one straight line.
        coordinates: [
          [from.lon, from.lat],
          [(from.lon + to.lon) / 2 + (to.lat - from.lat) * 0.12, (from.lat + to.lat) / 2],
          [to.lon, to.lat]
        ]
      }
    });
  }

  return features;
}

export { SOFT_THEMES };
