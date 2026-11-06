// Build: TypeScript + esbuild -> dist/ with content-hashed assets and an
// index.html that references them, plus the Node conformance entry.
// No service worker, by design (docs/ARCHITECTURE.md §13).
import * as esbuild from 'esbuild';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const dist = join(here, 'dist');

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });

const web = await esbuild.build({
  absWorkingDir: here,
  entryPoints: ['src/main.ts', 'src/app.css'],
  bundle: true,
  minify: true,
  sourcemap: true,
  format: 'esm',
  target: ['es2022'],
  platform: 'browser',
  outdir: 'dist',
  entryNames: '[name].[hash]',
  metafile: true,
  logLevel: 'warning',
});

let js = null;
let css = null;
for (const [out, meta] of Object.entries(web.metafile.outputs)) {
  if (meta.entryPoint === 'src/main.ts') js = out.replace(/^dist\//, '');
  if (meta.entryPoint === 'src/app.css') css = out.replace(/^dist\//, '');
}
if (!js || !css) throw new Error('build: expected a js and a css output');

const template = await readFile(join(here, 'index.html'), 'utf8');
const html = template.replace('{{APP_JS}}', js).replace('{{APP_CSS}}', css);
if (html.includes('{{')) throw new Error('build: unreplaced placeholder in index.html');
await writeFile(join(dist, 'index.html'), html);

await esbuild.build({
  absWorkingDir: here,
  entryPoints: ['src/conformance.ts'],
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: ['node24'],
  outfile: 'dist/conformance.js',
  logLevel: 'warning',
});

const outputs = Object.keys(web.metafile.outputs).concat(['dist/index.html', 'dist/conformance.js']);
for (const o of outputs.sort()) console.log(o);
