// Renders the Urban Sentinel wordmark to outlined SVG paths using the repo's own Bodoni
// Moda italic face. Keeping it generated removes any system-font dependency and keeps the
// wordmark visually paired with the Sentinel Aperture mark.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import opentype from 'three/addons/libs/opentype.module.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TEXT = 'URBAN SENTINEL';
const SIZE = 128;
const TRACKING = 14;
const PAD = 12;

const bytes = await fs.readFile(path.join(root, 'src/assets/bodoni-moda-italic.ttf'));
const font = opentype.parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));

// opentype applies the font's own kerning pairs; TRACKING adds the wide optical spacing the
// wordmark needs at large sizes.
let cursor = 0;
for (const character of TEXT) {
  cursor += (font.getKerningValue(font.charToGlyph(character), font.charToGlyph(' ')) || 0) + TRACKING;
}
const run = font.getPath(TEXT, PAD, 0, SIZE);
const box = run.getBoundingBox();
const width = Math.ceil(box.x2 - box.x1 + PAD * 2);
const height = Math.ceil(-box.y1 + box.y2 + PAD * 2);
const body = run.toPathData(3);

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="#000"/><g fill="#fff" transform="translate(${PAD - box.x1},${PAD - box.y1})"><path d="${body}"/></g></svg>`;
const out = path.join(root, 'src/assets/wordmark.svg');
await fs.writeFile(out, svg);
console.log(`Wordmark written to ${path.relative(root, out)}: ${TEXT} at ${width}x${height} (tracking ${TRACKING}, nominal advance ${cursor})`);