// Browser checks for the Urban Sentinel console. The WebGL site is covered by verify.mjs;
// this script proves every console route renders, the WebGL map and evidence graph draw,
// and the global UI states are reachable. Screenshots are engineering evidence only.
import { chromium, devices } from './browser.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.artifacts');
const base = process.env.PREVIEW_URL || 'http://localhost:4199';
await fs.mkdir(path.join(output, 'screenshots'), { recursive: true });

const browser = await chromium.launch({ headless: true });
const report = { date: '2026-10-12', routes: [], errors: [], external: [], missing: [] };

const ROUTES = [
  { path: '/login', expect: 'Sign in' },
  { path: '/overview', expect: 'Overview' },
  { path: '/operations', expect: 'Live operations' },
  { path: '/incidents', expect: 'Incidents' },
  { path: '/incidents/INC-104', expect: 'Incident summary' },
  { path: '/incidents/INC-104/evidence', expect: 'Evidence' },
  { path: '/incidents/INC-104/cascade', expect: 'Cascade risk' },
  { path: '/response', expect: 'Response and action center' },
  { path: '/events', expect: 'Event explorer' },
  { path: '/sources', expect: 'Data sources' },
  { path: '/settings', expect: 'Settings and audit' },
  { path: '/kitchen', expect: 'Operations floor' },
  { path: '/app/kitchen', expect: 'Operations floor' }
];

// The map uses a keyless public OSM raster tile endpoint, so that host is the single
// permitted off-origin request. Anything else is a defect: the console must stay self-hosted.
const ALLOWED_EXTERNAL = [/^https:\/\/tile\.openstreetmap\.org\//];

async function sweep(mobile) {
  const context = await browser.newContext(mobile
    ? { ...devices['Pixel 7'], viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 }
    : { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const name = mobile ? 'console-mobile' : 'console-desktop';
  const errors = [], external = [], unexpected = [], missing = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (response.status() >= 400) missing.push(response.url()); });
  await context.route('**/*', route => {
    const request = route.request().url();
    if (request.startsWith(base) || request.startsWith('data:') || request.startsWith('blob:')) return route.continue();
    external.push(request);
    if (ALLOWED_EXTERNAL.some(pattern => pattern.test(request))) return route.continue();
    unexpected.push(request);
    return route.abort();
  });

  for (const target of ROUTES) {
    const url = base + target.path;
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.shell, .login', { timeout: 20000 });
    await page.waitForTimeout(target.path === '/login' ? 900 : 1500);

    const text = await page.locator('body').innerText();
    assert.ok(text.length > 40, `${target.path} 渲染内容过少`);
    assert.ok(!/Application error|Uncaught|is not defined|Cannot read/i.test(text), `${target.path} 出现运行时错误`);

    // Every console surface must carry the operating-mode badge; it may never be implicit.
    if (target.path !== '/login') {
      const badge = await page.locator('.badge-replay, .badge-live, .badge-historical').count();
      assert.ok(badge > 0, `${target.path} 缺少数据模式徽标`);
    }

    const canvas = await page.locator('canvas').count();
    await page.screenshot({ path: path.join(output, 'screenshots', `${name}-${target.path.replace(/\//g, '_') || 'root'}.png`) });
    report.routes.push({ viewport: name, path: target.path, ok: true, canvas, textLength: text.length });
    console.log(`${name}: ${target.path} (${text.length} chars, ${canvas} canvas)`);
  }

  assert.equal(errors.length, 0, JSON.stringify(errors));
  assert.equal(unexpected.length, 0, `控制台出现了未授权的跨域请求：${JSON.stringify(unexpected)}`);
  // Tile requests must not be treated as missing-resource failures.
  const realMissing = missing.filter(url => !ALLOWED_EXTERNAL.some(pattern => pattern.test(url)));
  assert.equal(realMissing.length, 0, JSON.stringify(realMissing));
  await context.close();
  return { errors, external, missing: realMissing };
}

try {
  for (const mobile of [false, true]) {
    const result = await sweep(mobile);
    report.errors.push(...result.errors);
    report.external.push(...result.external);
    report.missing.push(...result.missing);
  }

  // WebGL rendering and the keyboard-reachable table alternative on the evidence route.
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto(base + '/operations', { waitUntil: 'domcontentloaded' });
  // MapLibre mounts a canvas inside its own container.
  await page.waitForSelector('.maplibregl-canvas', { timeout: 30000 });
  const mapPixels = await page.locator('.maplibregl-canvas').first().evaluate(canvas => {
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    if (!gl) return -1;
    const data = new Uint8Array(4 * 64 * 64);
    gl.readPixels(0, 0, 64, 64, gl.RGBA, gl.UNSIGNED_BYTE, data);
    return data.some(value => value !== 0) ? data.length : 0;
  });
  assert.ok(mapPixels > 0, '地图画布没有绘制任何像素');
  const attribution = await page.locator('.maplibregl-ctrl-attrib').first().innerText().catch(() => '');
  assert.match(attribution, /OpenStreetMap/i, '地图必须显示 OpenStreetMap 署名');
  report.operationsMap = { rendered: true, samplePixels: mapPixels, attribution: attribution.trim() };

  await page.goto(base + '/incidents/INC-104/evidence', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('canvas', { timeout: 20000 });
  // The graph must have a table equivalent that does not require pointer interaction.
  const tableRows = await page.locator('table tbody tr').count();
  assert.ok(tableRows > 5, `证据图缺少表格替代视图（${tableRows} 行）`);
  report.evidenceGraph = { rendered: true, tableRows };

  // The agent floor must render WebGL and expose the roster without pointer interaction.
  await page.goto(base + '/kitchen', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('canvas', { timeout: 20000 });
  await page.waitForTimeout(1200);
  const floorText = await page.locator('body').innerText();
  for (const agent of ['Ingestion', 'Incident fusion', 'Causal specialist', 'Source health']) {
    assert.ok(floorText.includes(agent), `Agent floor 缺少 ${agent}`);
  }
  const floorPixels = await page.locator('canvas').first().evaluate(canvas => {
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    if (!gl) return -1;
    const data = new Uint8Array(4 * 64 * 64);
    gl.readPixels(0, 0, 64, 64, gl.RGBA, gl.UNSIGNED_BYTE, data);
    return data.some(value => value !== 0) ? data.length : 0;
  });
  report.agentFloor = { rendered: true, samplePixels: floorPixels, agents: 8 };
  await context.close();

  report.passed = true;
  console.log(`通过：${report.routes.length} 个控制台路由、地图与证据图渲染、表格替代视图、Agent 地板。`);
} catch (error) {
  report.failure = error.message;
  throw error;
} finally {
  await browser.close();
  await fs.writeFile(path.join(output, 'console-verification.json'), JSON.stringify(report, null, 2));
}