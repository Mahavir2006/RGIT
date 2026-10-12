// Category glyphs.
//
// One authored set of 16 marks, drawn on a 24x24 grid with a consistent stroke weight. The same
// markup renders in three places: the MapLibre badge on the map, the filter panel row, and the
// legend. Sharing the artwork is the point - a category must not be one shape in a panel and a
// different shape on the map, or the operator has to learn the vocabulary twice.
//
// Authored here rather than pulled from an icon package so the map, the panel and the legend
// cannot drift apart, and so nothing ships as an opaque binary sprite.
import { CATEGORIES } from '../data/taxonomy.js';

// Marks are silhouette-first: they have to stay distinguishable at 14-18px over a raster
// basemap, so they avoid small interior detail and rely on outline rather than fill.
const PATHS = {
  // Waves under a falling drop: surface water standing on a road.
  flooding: '<path d="M3 16.2c1.8-1.5 3.2-1.5 5 0s3.2 1.5 5 0 3.2-1.5 5 0"/><path d="M3 20.4c1.8-1.5 3.2-1.5 5 0s3.2 1.5 5 0 3.2-1.5 5 0"/><path d="M12 2.8v6.4"/><path d="M9.6 6.6 12 9l2.4-2.4"/>',

  // Barrier with legs and a ground line: a closed road.
  road_blockage: '<path d="M3.5 8.5h17"/><path d="M3.5 14h17"/><path d="M6.5 8.5V19"/><path d="M17.5 8.5V19"/><path d="M2.5 19h19"/>',

  // Two wheels under a roofline.
  traffic: '<path d="M4.2 16.2h15.6"/><path d="M5.2 16.2 7 10.8h10l1.8 5.4"/><path d="M7.6 10.8 8.6 7.4h6.8l1 3.4"/><circle cx="7.6" cy="16.4" r="1.7"/><circle cx="16.4" cy="16.4" r="1.7"/>',

  // Megaphone with sound arcs.
  protest: '<path d="M3.5 9.6v4.8a1 1 0 0 0 1 1H8l8 4.2V4.4L8 8.6H4.5a1 1 0 0 0-1 1Z"/><path d="M19.2 8.4a5 5 0 0 1 0 7.2"/>',

  // Two figures at different depths.
  procession: '<circle cx="9" cy="7.4" r="2.6"/><path d="M3.6 20v-1.6A4.4 4.4 0 0 1 8 14h2a4.4 4.4 0 0 1 4.4 4.4V20"/><circle cx="17.2" cy="9.2" r="2"/><path d="M15.6 20v-1.6a3.2 3.2 0 0 1 3.2-3.2h.4a3.2 3.2 0 0 1 3.2 3.2V20"/>',

  // Cross inside a ring: a medical destination under access pressure.
  emergency_access: '<circle cx="12" cy="12" r="8.6"/><path d="M12 7.6v8.8M7.6 12h8.8"/>',

  // Flame with an inner tongue.
  fire_hazard: '<path d="M12 2.6c3.6 3.4 5.8 6 5.8 9a5.8 5.8 0 0 1-11.6 0c0-1.8.8-3.4 2.3-4.9.5 1.3 1.3 2.2 2.4 2.6-.4-2.5.3-4.6 1.1-6.7Z"/>',

  // Carriage front with a destination band and bogies.
  transit: '<path d="M6.4 3h11.2a2 2 0 0 1 2 2v8.8a3 3 0 0 1-3 3H7.4a3 3 0 0 1-3-3V5a2 2 0 0 1 2-2Z"/><path d="M4.4 10.2h15.2"/><path d="M8.6 21.2 10.4 18M15.4 21.2 13.6 18"/><circle cx="9" cy="13.4" r=".9"/><circle cx="15" cy="13.4" r=".9"/>',

  // Bolt.
  power: '<path d="M13.6 2.2 4.4 13.8h6.6l-.6 8 9.2-11.6h-6.6l.6-8Z"/>',

  // Culvert pipe with flow inside it and drops falling clear of the barrel. A vessel shape was
  // avoided here: an earlier bowl-and-legs draft read as a drinking glass at badge size.
  drainage: '<path d="M5.2 8.6h13.6a3.4 3.4 0 0 1 0 6.8H5.2a3.4 3.4 0 0 1 0-6.8Z"/><path d="M8.4 12h7.2"/><path d="M13.4 10 15.6 12l-2.2 2"/><path d="M7.6 15.4v3.8M12 15.4v5M16.4 15.4v3.8"/>',

  // Three flow lines with alternating hooks. Deliberately no diagonal: the sensor mark is
  // defined by its slash, and two diagonals on the map would be read as the same thing.
  air_quality: '<path d="M3.2 7.4h9.6a2.5 2.5 0 1 0-2.5-2.5"/><path d="M3.2 12h13.4a2.5 2.5 0 1 1-2.5 2.5"/><path d="M3.2 16.6h6.6"/>',

  // Cloud with falling rain.
  weather: '<path d="M7.2 15.2a4.1 4.1 0 0 1 .6-8.1 5.6 5.6 0 0 1 10.6 2.5 3.1 3.1 0 0 1-.6 5.6Z"/><path d="M8.6 18.4 7.6 21M12 18.4 11 21M15.4 18.4l-1 2.6"/>',

  // Hard hat.
  infrastructure: '<path d="M3.8 15.8h16.4"/><path d="M5.4 15.8a6.6 6.6 0 0 1 13.2 0"/><path d="M12 9.2V6.2"/><path d="M8.8 6.2h6.4"/><path d="M2.8 19.4h18.4"/>',

  // Newspaper.
  reports: '<path d="M4 4.6h12.6v14.8H5.4a1.4 1.4 0 0 1-1.4-1.4Z"/><path d="M16.6 9h3v9a1.4 1.4 0 0 1-1.4 1.4h-1.6"/><path d="M7 8.2h6.6M7 11.6h6.6M7 15h4"/>',

  // Antenna arcs crossed out: the reading is missing, not zero.
  sensor_health: '<path d="M8.6 8.9a5 5 0 0 1 6.6-.4"/><path d="M5.4 5.7a9 9 0 0 1 11.4-.9"/><path d="M12 17.8h.01"/><path d="M3.6 3.6 20.4 20.4"/>',

  // Downstream chain: a cause propagating to a consequence.
  cascade: '<circle cx="6.4" cy="5.6" r="2.2"/><circle cx="17.6" cy="12" r="2.2"/><circle cx="6.4" cy="18.4" r="2.2"/><path d="M8.6 5.6H11a4 4 0 0 1 4 4v.2"/><path d="M15.4 16.2V16a4 4 0 0 0-4-4H8.6"/>'
};

const DOT_FILL = new Set(['transit']);

/** Inner markup for one category, on the 24x24 authoring grid. */
export function categoryGlyphBody(categoryId) {
  return PATHS[categoryId] ?? PATHS.reports;
}

/** Standalone stroked SVG, used by the filter panel and the legend. */
export function categoryGlyphSvg(categoryId, { size = 16, colour = 'currentColor', width = 2 } = {}) {
  const fill = DOT_FILL.has(categoryId) ? colour : 'none';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="${size}" height="${size}" fill="${fill}" stroke="${colour}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${categoryGlyphBody(categoryId)}</svg>`;
}

const BADGE_BOX = 48;
// The glyph is authored on a 24x24 grid; the badge is 48x48, so the mark sits at 1:1 scale
// centred inside it, leaving a 12px margin on every side.
const GLYPH_OFFSET = (BADGE_BOX - 24) / 2;

// The map badge is a rounded tile in the category colour carrying a white mark. Colour and shape
// are both carried, so the category survives greyscale printing and colour-vision differences.
function badgeSvg(categoryId, { colour, rim }) {
  const body = categoryGlyphBody(categoryId);
  // A handful of marks use filled dots (train lights, antenna tip). Those need the fill forced
  // to white, because the group sets fill:none for the stroked marks.
  const filled = DOT_FILL.has(categoryId)
    ? body.replace(/<circle /g, '<circle fill="#ffffff" stroke="#ffffff" ')
    : body;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${BADGE_BOX} ${BADGE_BOX}" width="${BADGE_BOX}" height="${BADGE_BOX}">
    <rect x="1.5" y="1.5" width="${BADGE_BOX - 3}" height="${BADGE_BOX - 3}" rx="13" fill="${colour}" stroke="${rim}" stroke-width="3"/>
    <g transform="translate(${GLYPH_OFFSET} ${GLYPH_OFFSET})" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${filled}</g>
  </svg>`;
}

// Rendered at 2x the nominal badge so the mark stays crisp when MapLibre scales it by severity.
const RASTER = BADGE_BOX * 2;

function svgToImageData(svgText) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = RASTER;
      canvas.height = RASTER;
      const context = canvas.getContext('2d');
      context.drawImage(image, 0, 0, RASTER, RASTER);
      // ImageData rather than the canvas itself: MapLibre needs pixel data it can copy into
      // the WebGL texture, and getImageData avoids any tainted-canvas concern.
      resolve(context.getImageData(0, 0, RASTER, RASTER));
    };
    image.onerror = () => reject(new Error('glyph raster failed'));
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgText)}`;
  });
}

/**
 * Register one badge image per category on the map.
 *
 * Must be awaited before any layer references these images, otherwise MapLibre errors on a
 * missing sprite. A category that fails to rasterise falls back to the reports mark rather than
 * leaving an invisible layer.
 */
export async function registerCategoryBadges(map, { rim = '#ffffff' } = {}) {
  await Promise.all(CATEGORIES.map(async category => {
    try {
      const data = await svgToImageData(badgeSvg(category.id, { colour: category.colour, rim }));
      if (!map.hasImage(`cat-${category.id}`)) map.addImage(`cat-${category.id}`, data);
    } catch {
      if (!map.hasImage('cat-reports')) map.addImage('cat-reports', {
        width: RASTER, height: RASTER, data: new Uint8Array(RASTER * RASTER * 4)
      });
    }
  }));
}

export const BADGE_RASTER = RASTER;