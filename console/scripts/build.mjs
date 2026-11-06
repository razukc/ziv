#!/usr/bin/env node
// Build the console into dist/: content-hashed bundles, manifest.json and an
// index.html that references them. Fails when src/generated/wire.ts is stale
// against ../schema (scripts/gen-types.mjs --check).
//
//   ZIV_CONSOLE_API_BASE=https://relay.example  node scripts/build.mjs
//
// Exported for scripts/dev.mjs, which runs the same pipeline in watch mode.

import * as esbuild from "esbuild";
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve, basename } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const root = resolve(here, "..");
export const outdir = resolve(root, "dist");

export function apiBaseFromEnv() {
  const raw = (process.env.ZIV_CONSOLE_API_BASE ?? "").trim().replace(/\/+$/, "");
  if (raw && !/^https?:\/\//.test(raw)) {
    throw new Error(`ZIV_CONSOLE_API_BASE must be an absolute http(s) origin, got "${raw}"`);
  }
  return raw;
}

export function checkTypesFresh() {
  const r = spawnSync(process.execPath, [resolve(here, "gen-types.mjs"), "--check"], { stdio: "inherit" });
  if (r.status !== 0) throw new Error("generated types are stale; run `npm run gen:types`");
}

export function csp(apiBase) {
  const connect = apiBase ? `'self' ${new URL(apiBase).origin}` : "'self'";
  return [
    "default-src 'none'",
    "script-src 'self'",
    "style-src 'self'",
    `connect-src ${connect}`,
    "img-src 'self'",
    "font-src 'self'",
    "base-uri 'none'",
    "form-action 'none'",
    "object-src 'none'",
    "manifest-src 'self'",
  ].join("; ");
}

/** esbuild options shared by build and dev. */
export function buildOptions(apiBase, { minify = true } = {}) {
  return {
    absWorkingDir: root,
    entryPoints: { app: "src/main.ts", styles: "src/styles.css" },
    bundle: true,
    minify,
    sourcemap: true,
    format: "esm",
    target: ["es2022", "chrome110", "firefox115", "safari16"],
    outdir,
    entryNames: "[name]-[hash]",
    assetNames: "[name]-[hash]",
    metafile: true,
    legalComments: "none",
    charset: "utf8",
    logLevel: "info",
    define: { __API_BASE__: JSON.stringify(apiBase) },
  };
}

/** From the metafile, write manifest.json and index.html. Returns the manifest. */
export function finish(metafile, apiBase) {
  const manifest = {};
  for (const [outPath, meta] of Object.entries(metafile.outputs)) {
    const file = basename(outPath);
    if (meta.entryPoint) {
      const logical = meta.entryPoint === "src/main.ts" ? "app.js" : meta.entryPoint === "src/styles.css" ? "styles.css" : basename(meta.entryPoint);
      manifest[logical] = file;
    } else if (outPath.endsWith(".map")) {
      const src = file.replace(/\.map$/, "");
      const logicalOwner = Object.entries(manifest).find(([, hashed]) => hashed === src)?.[0];
      if (logicalOwner) manifest[`${logicalOwner}.map`] = file;
    }
  }
  if (!manifest["app.js"] || !manifest["styles.css"]) {
    throw new Error(`build produced no app.js/styles.css entry: ${JSON.stringify(Object.keys(metafile.outputs))}`);
  }
  // Maps are emitted after their bundles; resolve any left unmapped.
  for (const outPath of Object.keys(metafile.outputs)) {
    if (!outPath.endsWith(".map")) continue;
    const file = basename(outPath);
    const owner = Object.entries(manifest).find(([k, v]) => !k.endsWith(".map") && v === file.replace(/\.map$/, ""))?.[0];
    if (owner) manifest[`${owner}.map`] = file;
  }
  const template = readFileSync(resolve(root, "src", "index.html"), "utf8");
  const html = template
    .replaceAll("{{csp}}", csp(apiBase))
    .replaceAll("{{app.js}}", `./${manifest["app.js"]}`)
    .replaceAll("{{styles.css}}", `./${manifest["styles.css"]}`);
  if (/\{\{[^}]+\}\}/.test(html)) throw new Error("index.html template has an unfilled placeholder");
  mkdirSync(outdir, { recursive: true });
  writeFileSync(resolve(outdir, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  writeFileSync(resolve(outdir, "index.html"), html);
  return manifest;
}

export async function buildOnce() {
  checkTypesFresh();
  const apiBase = apiBaseFromEnv();
  rmSync(outdir, { recursive: true, force: true });
  mkdirSync(outdir, { recursive: true });
  const result = await esbuild.build(buildOptions(apiBase));
  const manifest = finish(result.metafile, apiBase);
  return { manifest, apiBase };
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  try {
    const { manifest, apiBase } = await buildOnce();
    console.log(`built dist/ for ${apiBase || "same-origin relay"}:`);
    for (const [k, v] of Object.entries(manifest)) console.log(`  ${k.padEnd(16)} -> ${v}`);
    console.log("  index.html, manifest.json");
  } catch (err) {
    console.error(err instanceof Error ? err.message : err);
    process.exit(1);
  }
}
