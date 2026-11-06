#!/usr/bin/env node
// Generate src/generated/wire.ts from ../schema/*.json (the wire contract
// emitted by `python -m ziv.wire schema/`).
//
//   node scripts/gen-types.mjs           write the file
//   node scripts/gen-types.mjs --check   exit 1 if the recorded schema hash
//                                        no longer matches schema/ (the build
//                                        runs this, so stale types fail it)
//
// Every schema file carries its own `$defs` (Kind, Reason, State, ...). They
// are identical across files, so they are hoisted into one root `$defs` and
// compiled once; a differing definition under the same name is an error, not
// a silent pick.

import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const schemaDir = resolve(here, "..", "..", "schema");
const outFile = resolve(here, "..", "src", "generated", "wire.ts");
const check = process.argv.includes("--check");

const files = readdirSync(schemaDir).filter((f) => f.endsWith(".json")).sort();
if (files.length === 0) {
  console.error(`gen-types: no schema files in ${schemaDir}`);
  process.exit(1);
}

const hash = createHash("sha256");
const sources = files.map((name) => {
  const text = readFileSync(join(schemaDir, name), "utf8");
  hash.update(name);
  hash.update("\0");
  hash.update(text);
  hash.update("\0");
  return { name, json: JSON.parse(text) };
});
const schemaHash = `sha256:${hash.digest("hex")}`;

if (check) {
  if (!existsSync(outFile)) {
    console.error(`gen-types: ${outFile} is missing; run: npm run gen:types`);
    process.exit(1);
  }
  const recorded = /^\/\/ schema-hash: (\S+)$/m.exec(readFileSync(outFile, "utf8"))?.[1];
  if (recorded !== schemaHash) {
    console.error(
      `gen-types: generated types are stale (recorded ${recorded ?? "none"}, schema/ is ${schemaHash}); run: npm run gen:types`,
    );
    process.exit(1);
  }
  console.log(`gen-types: types match schema/ (${schemaHash})`);
  process.exit(0);
}

// --- hoist ----------------------------------------------------------------

function canonical(value) {
  return JSON.stringify(sortKeys(value));
}
function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((k) => [k, sortKeys(value[k])]),
    );
  }
  return value;
}
function pascal(fileName) {
  return fileName
    .replace(/\.json$/, "")
    .split(/[-_]/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join("");
}

// Pydantic titles every field ("Pace Ms", "Id"); json-schema-to-typescript
// would turn each into its own alias (Id, Id1, Id2 ...). Only the named
// definitions keep their titles.
function stripPropertyTitles(schema) {
  if (schema && typeof schema === "object" && schema.properties) {
    for (const prop of Object.values(schema.properties)) {
      if (prop && typeof prop === "object") {
        delete prop.title;
        // A `$ref` with a sibling `default` is otherwise inlined as a fresh
        // type (Kind1, Kind2 ...). Defaults do not change the type.
        if ("$ref" in prop) delete prop.default;
      }
    }
  }
  return schema;
}

const defs = {};
function addDef(name, schema, from) {
  schema = stripPropertyTitles(schema);
  if (name in defs) {
    if (canonical(defs[name]) !== canonical(schema)) {
      throw new Error(`gen-types: "${name}" differs between files (seen again in ${from}); the schema export is inconsistent`);
    }
    return;
  }
  defs[name] = schema;
}

// Names for the two untitled files (discriminated unions of frames).
const fileNames = {
  "device-frames-down.json": "DeviceFrameDown",
  "device-frames-up.json": "DeviceFrameUp",
};

for (const { name, json } of sources) {
  const { $defs = {}, $schema: _s, $comment: _c, ...body } = json;
  for (const [k, v] of Object.entries($defs)) addDef(k, v, name);
  const typeName = body.title ?? fileNames[name] ?? pascal(name);
  if (!body.title) body.title = typeName;
  addDef(typeName, body, name);
}

const root = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "WireRoot",
  type: "object",
  additionalProperties: false,
  properties: {},
  $defs: defs,
};

// --- compile ----------------------------------------------------------------

const { compile } = await import("json-schema-to-typescript");
let ts = await compile(root, "WireRoot", {
  bannerComment: "",
  additionalProperties: false,
  strictIndexSignatures: true,
  unreachableDefinitions: true,
  declareExternallyReferenced: true,
  format: false,
});
// The root object exists only to carry $defs; drop its empty interface.
ts = ts.replace(/export interface WireRoot \{\s*\}\s*/m, "");

// Runtime lists for every string enum, so the client can validate a value
// off the wire (`isReason(x)`) without a second copy of the vocabulary.
const enums = Object.entries(defs)
  .filter(([, v]) => v.type === "string" && Array.isArray(v.enum))
  .map(([name, v]) => {
    const constName = `${name.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toUpperCase()}_VALUES`;
    const list = v.enum.map((e) => JSON.stringify(e)).join(", ");
    return `export const ${constName} = [${list}] as const;\n`;
  })
  .join("");

const header = [
  "// GENERATED by console/scripts/gen-types.mjs from schema/*.json. Do not edit.",
  "// Regenerate with `npm run gen:types`; the build fails when this hash is stale.",
  `// schema-hash: ${schemaHash}`,
  `// sources: ${files.join(", ")}`,
  "",
  "/* eslint-disable */",
  "",
].join("\n");

mkdirSync(dirname(outFile), { recursive: true });
writeFileSync(outFile, header + ts.trimEnd() + "\n\n" + enums, "utf8");
console.log(`gen-types: wrote ${outFile} (${schemaHash})`);
