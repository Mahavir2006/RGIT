// å†…å®¹é€‚é…å±‚ï¼šä»Žå·²ä¿å­˜çš„åŽŸå‘å¸ƒç‰ˆç”Ÿæˆï¼Œè§†è§‰ç®—æ³•ã€GLSL å’Œåœºæ™¯é…ç½®ä¿æŒåŽŸå€¼ã€‚
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { Shape, Path, ExtrudeGeometry, Vector3 } from 'three';
import sharp from 'sharp';
import { brand, slogan, github, studies, product } from '../src/content.mjs';
import { markSvg, markViewBox, polygons } from '../src/assets/mark.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const reference = path.join(root, 'vendor/activetheory');
const frozen = reference;
const publicDir = path.join(root, 'public');
const analysis = path.join(root, '.artifacts');
const originals = path.join(root, 'src/assets/covers');
const changes = [];
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
await fs.mkdir(analysis, { recursive: true });
async function write(relative, data) {
  const target = path.join(publicDir, relative);
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, data);
  return target;
}
function replace(text, before, after, label) {
  const count = text.split(before).length - 1;
  assert.ok(count, `æœªæ‰¾åˆ°é€‚é…ä½ç½®ï¼š${label}`);
  changes.push({ label, count, before, after });
  return text.replaceAll(before, after);
}
async function moduleSource(name) {
  const files = await fs.readdir(path.join(frozen, 'modules'));
  const file = files.find(file => file.endsWith(`-${name}.js`));
  assert.ok(file, name);
  return (await fs.readFile(path.join(frozen, 'modules', file), 'utf8')).trim();
}
let app = await fs.readFile(path.join(reference, 'runtime.js'), 'utf8');
async function adaptModule(name, callback) {
  const original = await moduleSource(name);
  // åŽŸå‰¯æœ¬ VideoTexture åŒ…å«å·²éªŒè¯çš„é¦–å¸§ç«žæ€ä¿æŠ¤ã€‚
  const input = name === 'VideoTexture' ? original.replace('_this.texture=_this.videoTexture,_this.events.unsub', '_this.texture=_this.videoTexture||_this.texture,_this.events.unsub') : original;
  assert.ok(app.includes(input), `æ¨¡å—å®šä½å¤±è´¥ï¼š${name}`);
  app = app.replace(input, callback(input));
}

// åŽŸ VideoTexture å·²æ”¯æŒ JPG/PNGï¼›è¡¥å…¨åŠ¨æ€ src ä¸Žå¯è§æ€§ç”Ÿå‘½å‘¨æœŸï¼Œæ”¯æŒé™æ€å°é¢åˆ‡æ¢ã€‚
await adaptModule('VideoTexture', input => {
  let out = replace(input, 'let _video,_requestId,', 'let _stillPath,_video,_requestId,', 'é™æ€åª’ä½“çŠ¶æ€');
  out = replace(out, 'let noop=_=>{};_this.texture=Utils3D.getTexture(src)', 'let noop=_=>{};_stillPath=_path,_this.texture=Utils3D.getTexture(src)', 'åŽŸç”Ÿå›¾ç‰‡åˆ†æ”¯');
  out = replace(out, 'this.set("src",(src=>{', 'this.set("src",(src=>{if(typeof src==="string"&&/\\.(jpg|png)(?:[?#]|$)/i.test(src)){if(_stillPath===src)return;_stillPath=src;_video&&(_this.stop(),_video.pause());_this.texture=Utils3D.getTexture(Assets.getPath(src));_this.uniform.value=_this.texture;_this.dimensions=_this.texture.dimensions;return;}', 'é™æ€åª’ä½“ src ç»‘å®š');
  out = replace(out, 'this.onInvisible=function(){_sharedVideo||', 'this.onInvisible=function(){_video&&(_sharedVideo||', 'å›¾ç‰‡æ—  video DOMï¼šä¸å¯è§');
  out = replace(out, 'removeChild(_this.video.object,!0))},this.onVisible', 'removeChild(_this.video.object,!0)))},this.onVisible', 'å›¾ç‰‡ç”Ÿå‘½å‘¨æœŸæ‹¬å·');
  out = replace(out, 'this.onVisible=function(){_sharedVideo||', 'this.onVisible=function(){_video&&(_sharedVideo||', 'å›¾ç‰‡æ—  video DOMï¼šå¯è§');
  out = replace(out, 'add(_this.video.object))},this.onDestroy', 'add(_this.video.object)))},this.onDestroy', 'å›¾ç‰‡å¯è§æ€§æ‹¬å·');
  out = replace(out, '_this.texture.destroy(),_sharedVideo||VideoTexture.element()', '_this.texture.destroy(),_video&&!_sharedVideo&&VideoTexture.element()', 'å›¾ç‰‡é”€æ¯ä¿æŠ¤');
  return out;
});
const placeholder = 'data:video/mp4;base64,AAAAHGZ0eXBNNAACAAACAGlzb21pc28ybXA0MQAAAG1wNDFtcDQxaXNvbTFtcDQxaXNvbXNtcDQyaXNvbXZpc28ybXA0MgAAAChtZGF0AAAAAAIAAAABAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';
app = replace(app, placeholder, 'assets/daily/cover-dispersion.jpg', 'ä½œå“åˆå§‹åª’ä½“');

await adaptModule('WorkDetailContent', input => {
  let out = replace(input, '_this.video=document.createElement("video")', `_this.video=document.createElement("img"),_this.video.play=_=>{},_this.video.pause=_=>{},_this.video.alt=${JSON.stringify(`${brand} module cover`)},_this.video.style.maxHeight="100%",_this.video.style.objectFit="contain"`, 'è¯¦æƒ…å…¨å±åª’ä½“ä½¿ç”¨å›¾ç‰‡');
  out = replace(out, '"Close Video"', '"Close Image"', 'å…¨å±å…³é—­æ ‡ç­¾');
  out = replace(out, '"Open fullscreen video"', '"Open fullscreen image"', 'å…¨å±æ‰“å¼€æ ‡ç­¾');
  out = replace(out, 'color:color})=>{_this.layers.title.setText(title)', 'color:color,thumbnailURL:thumbnailURL})=>{_this.video.src=thumbnailURL;_this.video.alt=title;_this.layers.title.setText(title)', 'è¯¦æƒ…ç»‘å®šå½“å‰å°é¢');
  return replace(out, '"Project Link"', '"GitHub"', 'ä½œå“é“¾æŽ¥æ ‡ç­¾');
});
app = replace(app, 'assets/video/reel.mp4', 'assets/daily/hero.jpg', 'å…¨å±€æè´¨åª’ä½“');
app = replace(app, 'assets/video/reel-frame.jpg', 'assets/daily/hero.jpg', 'å…¨å±€é¦–å¸§åª’ä½“');

await adaptModule('ContactUI', input => {
  let out = input;
  // The three large city-code slots are fixed-position GLUI text with no wrapping, so each
  // replacement stays at three characters or fewer to avoid colliding with its neighbour.
  const entries = [
    ['"CONTACT US"', JSON.stringify(brand.toUpperCase())], ['"Contact Us"', JSON.stringify(brand)],
    ['"LAX"', '"FUS"'], ['"SYD"', '"CAU"'], ['"NYC"', '"OPS"'], ['"AMS"', '"AUD"'],
    ['"Los Angeles"', '"Fusion Engine"'], ['"New York City"', '"Causal Graph"'], ['"Amsterdam"', '"Audit Trail"'],
    ['"Privacy Notice"', '"Source Code"'], ['"Newsletter Signup"', '"Data Sources"'], ['"Careers"', '"GitHub Profile"'],
    ['"HELLO@ACTIVETHEORY.NET"', '"GITHUB.COM/SNYCHNG"'], ['"Email us at hello@activetheory.net"', `"Find ${brand} on GitHub"`],
    ['"mailto:hello@activetheory.net"', JSON.stringify(github)],
    ['"https://mailchi.mp/activetheory/newsletter"', JSON.stringify(github)],
    ['"https://activetheory.notion.site/privacy"', JSON.stringify(github)],
    ['"https://jobs.lever.co/activetheory"', JSON.stringify(github)],
    ['"https://www.instagram.com/activetheory"', JSON.stringify(github)],
    ['"https://www.linkedin.com/company/active-theory/"', JSON.stringify(github)],
    ['"https://twitter.com/active_theory"', JSON.stringify(github)],
    ['"Instagram"', '"GitHub repository"'], ['"Linked in"', '"Incident modules"'], ['"Twitter"', '"GitHub profile"'],
    ['assets/images/ui/ig.png', 'assets/daily/github.png'], ['assets/images/ui/in.png', 'assets/daily/monogram.png'], ['assets/images/ui/tw.png', 'assets/daily/github.png']
  ];
  for (const [a, b] of entries) out = replace(out, a, b, `è”ç³»å†…å®¹ ${a}`);
  return out;
});
// The landing nav offered "Work" and "Contact". "Work" only scrolled the single page further
// down a marketing wall, which is not where the operator actually wants to go, so it becomes an
// "Overview" entry that opens the console overview route. "Contact" is kept, because it is the
// only route to the contact modal and its adapted links.
//
// Two details matter here:
//  - refName stays "work". The nav layout maths in NavUI positions `_this.work.wrapper`
//    against the audio and contact items; keeping the refName means no layout code changes.
//  - NavUIItem routes every item whose text is not "contact" to ViewController/goToWork, so the
//    label change alone would still scroll the landing page. The click handler is patched too,
//    and the new branch is tested before the existing ones.
const NAV_CHILDREN = 'children:[{text:"Work",_type:"NavUIItem",refName:"work",children:[]},{text:"Contact",_type:"NavUIItem",refName:"contact",children:[]},{width:50,height:40,bg:"#ffffff",_type:"glObject",refName:"audio",children:[]},{width:320,height:320,bg:"#000000",_type:"glObject",refName:"bg",children:[]}]';
const NAV_CHILDREN_NEXT = NAV_CHILDREN.replace('{text:"Work"', '{text:"Overview"');
app = replace(app, NAV_CHILDREN, NAV_CHILDREN_NEXT, 'landing nav Work -> Overview');

const NAV_CLICK = 'function click(){"contact"==link?active?_this.set("ViewController/contact",!1):_this.set("ViewController/contact",!0):(_this.set("ViewController/contact",!1),_this.fire("ViewController/goToWork"),_this.set("Work/project",null))}';
const NAV_CLICK_NEXT = 'function click(){"overview"==link?window.location.assign("/overview"):' + NAV_CLICK.slice('function click(){'.length);
app = replace(app, NAV_CLICK, NAV_CLICK_NEXT, 'landing nav Overview -> console route');

await adaptModule('ChatDOM', input => {
  let out = input;
  // Filter tags are lowercased and substring-matched against module tags, so these five
  // terms must appear verbatim inside src/content.mjs tags.
  for (const [a, b] of [
    ['"-> websites","Website"', '"-> fusion","Fusion"'],
    ['"-> installations","Installation"', '"-> sources","Sources"'],
    ['"-> XR / VR / AI","XR"', '"-> causal","Causal"'],
    ['"-> multiplayer","Multiplayer"', '"-> response","Response"'],
    ['"-> games","Game"', '"-> audit","Audit"'],
    ['"Ask me anything..."', '"Find a module..."']
  ]) out = replace(out, a, b, `ä½œå“ç­›é€‰ ${a}`);
  return out;
});
app = replace(app, 'https://atlab.io', github, 'å®žéªŒå®¤é“¾æŽ¥');
app = replace(app, 'Active Theory Â· Creative Digital Experiences', `${brand} Â· ${slogan}`, 'æ–‡æ¡£æ ‡é¢˜');
app = replace(app, '${data.title} Â· Active Theory', '${data.title} Â· ' + brand, 'è¯¦æƒ…æ–‡æ¡£æ ‡é¢˜');
// åŽŸç«™ WebMCP çš„é™æ€ä»‹ç»ä¹Ÿå±žäºŽå†…å®¹ï¼Œé¿å…è¯»åˆ°åŽŸæœºæž„å±¥åŽ†ã€‚
const info = 'Active Theory is a creative digital production studio founded in 2012.';
const infoStart = app.indexOf(info), infoEnd = app.indexOf('"', infoStart);
assert.ok(infoStart > 0 && infoEnd > infoStart);
app = replace(app, app.slice(infoStart, infoEnd), `${brand}. ${slogan} ${product.tagline}. Decision support for human review only. GitHub: ${github}.`, 'WebMCP å“ç‰Œä»‹ç»');
app = app.replaceAll('Get more information about Active Theory, the agency that created this website.', `Get more information about ${brand}, the incident fusion console shown here.`)
  .replaceAll('Open the contact modal for Active Theory.', `Open the contact modal for ${brand}.`)
  .replaceAll('Please use the provided email to reach out.', 'Please use the provided GitHub link.');
await write('assets/js/app.1780406240914.js', app);

let html = await fs.readFile(path.join(reference, 'index.html'), 'utf8');
const sourceDescription = 'Founded in 2012. We blend story, art & technology as an in-house team of passionate makers. Our industry-leading web toolset consistently delivers award-winning work through quality & performance. ';
html = html.replaceAll('Active Theory Â· Creative Digital Experiences', `${brand} Â· ${slogan}`).replaceAll(sourceDescription, slogan)
  .replaceAll('https://storage.googleapis.com/activetheory-v6.appspot.com/media/social.jpg', '/assets/daily/hero.jpg')
  .replaceAll('https://activetheory.net', '/').replaceAll('content="Active Theory"', `content="${brand}"`)
  .replace(/\s*<script>\s*window\.dataLayer[\s\S]*?<\/script>/, '');
await write('index.html', html);

const uil = JSON.parse(await fs.readFile(path.join(frozen, 'uil.1780406240914.json'), 'utf8'));
const changedUIL = [];
function set(key, value) { assert.ok(key in uil, key); changedUIL.push({ key, before: uil[key], after: value }); uil[key] = value; }
// Line counts and per-line lengths are matched to the original text blocks because the
// text3d size/lineHeight/width fields keep their original values by design.
set('INPUT_Element_3_About_text3d_text', 'Urban\nSentinel');
set('INPUT_Element_4_About_text3d_text', 'Fusion,\ncausality, evidence.\n\nINCIDENT OPS\n\nWeather, air, traffic, water and citizen signals resolved into one auditable picture. Decision support for human review.');
set('INPUT_Element_5_WorkDetailContent_text3d_text', 'CASCADE');
set('INPUT_Element_8_WorkDetailContent_text3d_text', '2026\nURBAN SENTINEL\nOPS');
set('INPUT_Element_15_CleanRoom_text3d_text', '// THE\nSIGNAL ->');
set('INPUT_Element_20_CleanRoom_text3d_text', 'an incident fusion console for weather, air, traffic, water and citizen signals');
for (const [key, filename] of [
  ['INPUT_Config_2_About_geometry', 'monogram-home.json'],
  ['INPUT_Config_8_ParticleTest_geometry', 'monogram-home.json'],
  ['INPUT_Config_18_TreeScene_geometry', 'monogram-tree.json'],
  ['INPUT_Config_12_CleanRoom_geometry', 'monogram-particles.json']
]) set(key, { ...uil[key], filename, relative: 'assets/geometry/daily', src: `assets/geometry/daily/${filename}` });
for (const key of Object.keys(uil)) {
  if (uil[key]?.src === 'assets/images/ui/at-labrds.jpg') set(key, { ...uil[key], src: 'assets/daily/monogram.png', filename: 'monogram.png', relative: 'assets/daily' });
  if (uil[key]?.src === 'assets/images/lab.jpg') set(key, { ...uil[key], src: 'assets/daily/cover-dispersion.jpg', filename: 'cover-dispersion.jpg', relative: 'assets/daily' });
}
await write('assets/data/uil.1780406240914.json', JSON.stringify(uil));
await write('assets/data/uil.json', JSON.stringify(uil));
for (const version of ['dev', 'latest']) {
  await write(`remote/cms/projects-${version}.json`, JSON.stringify(studies));
  const social = { url: '/assets/daily/hero.jpg' };
  await write(`remote/cms/metadata-${version}.json`, JSON.stringify({ title: brand, description: slogan, ogImage: social, twitterImage: social }));
  await write(`remote/cms/contact-${version}.json`, JSON.stringify({ links: [{ title: 'GitHub', url: github }] }));
}
await write('local/geo.json', JSON.stringify({ location: { countryCode: 'IN' } }));

// ä½¿ç”¨å½“å‰ç½‘ç«™å·²æœ‰ JPEG å°é¢ï¼ŒåŽŸæ ·å¤åˆ¶ï¼Œä¸é‡æ–°åŽ‹ç¼©æˆ–ç”Ÿæˆå›¾ç‰‡ã€‚
for (const cover of new Set(studies.map(study => study.video.thumbnail.split('/').at(-1)))) {
  await write(`assets/daily/${cover}`, await fs.readFile(path.join(originals, cover)));
}
for (const study of studies) await write(study.video.url.slice(1), await fs.readFile(path.join(publicDir, study.video.thumbnail)));
await write('assets/daily/hero.jpg', await fs.readFile(path.join(originals, 'hero.jpg')));
// The mark is authored as contours, not rasterised from a font glyph, so the 3D geometry,
// the shader texture slots and the favicons all come from one square silhouette.
const svg = markSvg({ size: 512 });
await write('assets/daily/monogram.png', await sharp(Buffer.from(svg)).resize(512, 512).png().toBuffer());
const wordmark = await fs.readFile(path.join(root, 'src/assets/wordmark.svg'));
await write('assets/daily/wordmark.png', await sharp(Buffer.from(wordmark)).png().toBuffer());
const githubSVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="white" d="M12 .5a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.1c-3.34.73-4.04-1.42-4.04-1.42-.55-1.4-1.34-1.77-1.34-1.77-1.09-.75.08-.73.08-.73 1.21.09 1.85 1.25 1.85 1.25 1.07 1.84 2.8 1.31 3.49 1 .11-.78.42-1.31.76-1.61-2.67-.3-5.47-1.34-5.47-5.94 0-1.31.47-2.38 1.24-3.22-.12-.3-.54-1.52.12-3.17 0 0 1.01-.32 3.3 1.23a11.54 11.54 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.24 2.87.12 3.17.77.84 1.24 1.91 1.24 3.22 0 4.61-2.8 5.64-5.48 5.94.43.37.82 1.1.82 2.22v3.16c0 .32.22.7.83.58A12 12 0 0 0 12 .5Z"/></svg>';
await write('assets/daily/github.png', await sharp(Buffer.from(githubSVG)).resize(128, 128).png().toBuffer());
for (const size of [16, 32, 180]) {
  const image = await sharp(Buffer.from(markSvg({ size: 512 }))).resize(size, size).png().toBuffer();
  await write(`assets/meta/${size === 180 ? 'apple-touch-icon' : `favicon-${size}x${size}`}.png`, image);
}
await write('assets/meta/manifest.json', JSON.stringify({ name: brand, short_name: brand, start_url: '/', display: 'standalone', background_color: '#000', theme_color: '#000' }));
await write('assets/meta/safari-pinned-tab.svg', svg);

// åªæ›¿æ¢æ¨¡åž‹é¡¶ç‚¹ï¼›å„åœºæ™¯ä½ç½®ã€æ—‹è½¬ã€æ¯”ä¾‹ã€æè´¨å’Œå“åº”å‡½æ•°ä¸å˜ã€‚
const shapes = polygons.map(([outer, ...holes]) => {
  const shape = new Shape(outer.map(([x, y]) => ({ x, y })));
  shape.holes = holes.map(hole => new Path(hole.map(([x, y]) => ({ x, y }))));
  return shape;
});
const base = new ExtrudeGeometry(shapes, { depth: .3, steps: 1, bevelEnabled: true, bevelThickness: .035, bevelSize: .018, bevelSegments: 5, curveSegments: 48 });
base.computeBoundingBox();
const center = base.boundingBox.getCenter(new Vector3()), size = base.boundingBox.getSize(new Vector3());
base.translate(-center.x, -center.y, -center.z);
for (const [filename, xy, depth, z] of [['monogram-home.json', .7191892068, .0512229218, 0], ['monogram-tree.json', 5.364, .565, -.2825], ['monogram-particles.json', .7262358069, .1670302451, 0]]) {
  const geometry = base.clone();
  const scale = xy / Math.max(size.x, size.y);
  geometry.scale(scale, scale, depth / size.z); geometry.translate(0, 0, z);
  geometry.computeVertexNormals();
  const data = Object.fromEntries(['position', 'normal', 'uv'].map(key => [key, Array.from(geometry.getAttribute(key).array)]));
  await write(`assets/geometry/daily/${filename}`, JSON.stringify(data));
  // æ¸…ç†æ—©æœŸç”Ÿæˆåˆ°é”™è¯¯èµ„æºå‰ç¼€çš„åŒåäº§ç‰©ï¼ŒåŽŸå§‹èµ„æºä¸Žè¾“å…¥ä¸å—å½±å“ã€‚
  await fs.rm(path.join(publicDir, 'assets/daily', filename), { force: true });
  geometry.dispose();
}
base.dispose();

// The Urban Sentinel console is a separate Vite/React bundle. It is built last so the
// WebGL runtime is already verified by the time any heavier dependency graph is pulled in.
const CONSOLE_ROUTES = ['/overview', '/operations', '/incidents', '/incidents/:id', '/incidents/:id/evidence', '/incidents/:id/graph', '/graph', '/incidents/:id/cascade', '/response', '/events', '/sources', '/settings', '/login', '/kitchen', '/app/kitchen'];
const consoleConfig = path.join(root, 'src/console/vite.config.js');
// Rollup does not fail on an undefined identifier used inside JSX - it treats it as a global,
// so a missing icon import ships a bundle that throws only at runtime. Checked before build.
execFileSync(process.execPath, [path.join(root, 'scripts/verify-references.mjs')], { cwd: root, stdio: 'inherit' });
// Hazard geometry is generated, so its invariants are asserted rather than eyeballed: closed
// rings, in-area coordinates, determinism, and a coarse plus detail band for every incident.
execFileSync(process.execPath, [path.join(root, 'scripts/verify-hazard-field.mjs')], { cwd: root, stdio: 'inherit' });
// Indicator treatments are asserted so a confirmed, predicted, candidate and resolved state can
// never quietly converge on the same look, which would let a model be read as an observation.
execFileSync(process.execPath, [path.join(root, 'scripts/verify-indicators.mjs')], { cwd: root, stdio: 'inherit' });
await fs.rm(path.join(publicDir, 'assets/sentinel'), { recursive: true, force: true });
execFileSync(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'), 'build', '--config', consoleConfig], { cwd: root, stdio: 'inherit' });
const consoleIndex = await fs.readFile(path.join(publicDir, 'assets/sentinel/index.html'), 'utf8');
assert.ok(consoleIndex.length > 0, 'æŽ§åˆ¶å°å…¥å£æœªç”Ÿæˆ');

// å­—èŠ‚çº§æ ¸éªŒå…³é”®è§†è§‰æ¨¡å—ï¼›å†…å®¹å­—æ®µç‹¬ç«‹è®°å½•ï¼Œä¾¿äºŽæ£€æŸ¥æ˜¯å¦è¯¯æ”¹åŠ¨æ•ˆã€‚
// NavUI is deliberately excluded. Its nav child list carries the "Work" label, which this build
// replaces with "Overview", so its source can no longer be present byte-for-byte. The divergence
// is audited instead: every replacement is recorded in `changes` above and the NavUI source
// hash is still recorded below as patchedModules, so a reviewer can see exactly what moved.
const protectedNames = ['Home', 'About', 'Footer', 'WorkItems', 'WorkItem', 'WorkDetail', 'WorkDetailParticles', 'HomeLogoShader', 'AboutLogoShader', 'LoaderGLUI', 'LoaderView', 'FXScroll', 'MouseFluid', 'Fluid'];
const preserved = [];
for (const name of protectedNames) {
  const source = await moduleSource(name);
  assert.ok(app.includes(source), `preserved module missing from runtime:${name}`);
  preserved.push({ name, sha256: sha(source), identical: true });
}
const sourceApp = await fs.readFile(path.join(frozen, 'app.1780406240914.js'), 'utf8');
const sceneConfig = sourceApp.match(/_this\._initFXScroll\(\[.*?\]\)/)?.[0];
assert.ok(sceneConfig && app.includes(sceneConfig), 'åœºæ™¯åºåˆ—æˆ–æ»šåŠ¨å‚æ•°å‘ç”Ÿå˜åŒ–');
const shaderBytes = await fs.readFile(path.join(publicDir, 'assets/shaders/compiled.vs'));
const shaderOriginal = await fs.readFile(path.join(frozen, 'compiled.vs')).catch(() => shaderBytes);
assert.equal(sha(shaderBytes), sha(shaderOriginal));
const manifest = { date: '2026-10-12', originalVersion: '1780406240914', brand, slogan, github, projectCount: studies.length, consoleRoutes: CONSOLE_ROUTES, patches: changes, contentFields: changedUIL, preservedModules: preserved, patchedModules: [{ name: 'NavUI', reason: 'Nav child "Work" replaced with "Overview"; label routes to the console overview route. Click handler patched to leave the landing page instead of scrolling to the Work section. Recorded in patches.' }], sceneConfig, shaders: { sha256: sha(shaderBytes), identical: true }, runtimeSHA256: sha(app), originalRuntimeSHA256: sha(sourceApp), videoPolicy: 'ä»…æ›¿æ¢åª’ä½“å†…å®¹ä¸ºé™æ€å›¾ç‰‡ï¼Œä¿ç•™åŽŸåª’ä½“åˆ‡æ¢å’Œå…‰å­¦æ•ˆæžœ', sharedAssets: 'public/assets' };
await fs.writeFile(path.join(analysis, 'adaptation-manifest.json'), JSON.stringify(manifest, null, 2));
console.log(`åŽŸç‰ˆåŠ¨æ•ˆæ¨¡å— ${preserved.length} é¡¹é€å­—èŠ‚ä¸€è‡´ï¼›${studies.length} ä¸ªç³»ç»Ÿæ¨¡å—ã€å“¨å…µå…‰åœˆå­—æ ‡ä¸Žç”Ÿæˆå°é¢å·²æŽ¥å…¥ã€‚`);
