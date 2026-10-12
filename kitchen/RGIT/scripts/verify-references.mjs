// Catches JSX element / icon references that are neither imported nor locally defined.
//
// Rollup does not fail on an undefined identifier used in an expression - it treats it as a
// global and the error only appears at runtime. This walk catches that class of mistake, which
// a green build will happily ship.
import fs from 'node:fs/promises';
import path from 'node:path';

const ROOT = 'src/console/src';
const BUILTIN_GLOBALS = new Set(['React', 'Fragment', 'Math', 'JSON', 'Object', 'Array', 'String', 'Number', 'Boolean', 'Date', 'Map', 'Set', 'Promise', 'Error', 'RegExp', 'Symbol', 'Infinity', 'NaN', 'undefined', 'null', 'true', 'false', 'globalThis', 'console', 'window', 'document', 'navigator', 'location', 'fetch', 'URL', 'URLSearchParams', 'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval', 'requestAnimationFrame', 'cancelAnimationFrame', 'ResizeObserver', 'IntersectionObserver', 'MutationObserver', 'Image', 'Audio', 'CustomEvent', 'Event', 'FormData', 'Headers', 'Request', 'Response', 'Blob', 'File', 'FileReader', 'TextDecoder', 'TextEncoder', 'performance', 'structuredClone', 'queueMicrotask', 'Intl', 'WeakMap', 'WeakSet', 'Proxy', 'Reflect', 'BigInt', 'parseInt', 'parseFloat', 'isNaN', 'encodeURIComponent', 'decodeURIComponent']);

async function walk(dir) {
  const out = [];
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...await walk(full));
    else if (/\.jsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

let problems = 0;

for (const file of await walk(ROOT)) {
  const code = await fs.readFile(file, 'utf8');

  // Everything the module brought into scope by name.
  const declared = new Set(BUILTIN_GLOBALS);
  for (const m of code.matchAll(/import\s+([^;]+?)\s+from\s+['"][^'"]+['"]/g)) {
    const clause = m[1];
    const named = clause.match(/\{([^}]*)\}/);
    if (named) {
      for (const part of named[1].split(',')) {
        const name = part.trim().split(/\s+as\s+/).pop()?.trim();
        if (name) declared.add(name);
      }
    }
    const def = clause.replace(/\{[^}]*\}/, '').replace(/^,|,$/g, '').trim().split(',');
    for (const name of def) {
      const clean = name.trim().split(/\s+as\s+/).pop()?.trim();
      if (clean && !clean.startsWith('*')) declared.add(clean);
    }
  }
  // Locals: function/const/class/param declarations and destructured names.
  for (const m of code.matchAll(/\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)/g)) declared.add(m[1]);
  for (const m of code.matchAll(/\b(?:const|let|var)\s*\{([^}]*)\}\s*=/g)) {
    for (const part of m[1].split(',')) {
      // `{ icon: Icon }` binds Icon, not icon, so take the trailing name of the binding target.
      const name = part.split('=')[0].split(':').pop().trim();
      if (/^[A-Za-z_$][\w$]*$/.test(name)) declared.add(name);
    }
  }
  for (const m of code.matchAll(/\(([^)]*)\)\s*=>/g)) {
    for (const part of m[1].split(',')) {
      const name = part.split('=')[0].split(':').pop().trim();
      if (/^[A-Za-z_$][\w$]*$/.test(name)) declared.add(name);
    }
  }
  // Destructured function parameters: function f({ icon: Icon }) { ... }
  for (const m of code.matchAll(/\(\s*\{([^}]*)\}\s*\)\s*=>/g)) {
    for (const part of m[1].split(',')) {
      const name = part.split('=')[0].split(':').pop().trim();
      if (/^[A-Za-z_$][\w$]*$/.test(name)) declared.add(name);
    }
  }
  for (const m of code.matchAll(/\bfunction\s+[A-Za-z_$][\w$]*\s*\(\s*\{([^}]*)\}/g)) {
    for (const part of m[1].split(',')) {
      const name = part.split('=')[0].split(':').pop().trim();
      if (/^[A-Za-z_$][\w$]*$/.test(name)) declared.add(name);
    }
  }
  // Object literal keys used as <Icon> style values are values, not names, so nothing to add.

  // Capitalised identifiers referenced anywhere - JSX elements and icon references alike.
  const referenced = new Map();
  for (const m of code.matchAll(/<([A-Z][\w$.]*)/g)) {
    if (!referenced.has(m[1])) referenced.set(m[1], m.index);
  }
  for (const m of code.matchAll(/\bicon:\s*([A-Z][\w$]*)/g)) {
    if (!referenced.has(m[1])) referenced.set(m[1], m.index);
  }

  const missing = [...referenced.keys()].filter(name => !declared.has(name.split('.')[0]));
  if (missing.length) {
    problems += missing.length;
    const lineOf = index => code.slice(0, index).split('\n').length;
    console.log(`${file}`);
    for (const name of missing) console.log(`  line ${lineOf(referenced.get(name))}: ${name}`);
  }
}

console.log(problems ? `\n${problems} unresolved reference(s)` : '\nNo unresolved capitalised references.');
process.exit(problems ? 1 : 0);