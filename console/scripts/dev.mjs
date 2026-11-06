#!/usr/bin/env node
// Development loop: regenerate types, esbuild in watch mode writing dist/,
// and the mock relay serving dist/ at the same origin (so the strict CSP and
// same-origin API calls behave exactly as in production).
//
//   npm run dev            http://127.0.0.1:8787/
//   ZIV_MOCK_PORT=9000 npm run dev

import * as esbuild from "esbuild";
import { spawnSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { apiBaseFromEnv, buildOptions, finish, outdir } from "./build.mjs";
import { createMockServer } from "../mock/server.mjs";

const here = dirname(fileURLToPath(import.meta.url));

const gen = spawnSync(process.execPath, [resolve(here, "gen-types.mjs")], { stdio: "inherit" });
if (gen.status !== 0) process.exit(gen.status ?? 1);

const apiBase = apiBaseFromEnv();
rmSync(outdir, { recursive: true, force: true });
mkdirSync(outdir, { recursive: true });

const ctx = await esbuild.context({
  ...buildOptions(apiBase, { minify: false }),
  plugins: [
    {
      name: "manifest-and-index",
      setup(build) {
        build.onEnd((result) => {
          if (result.errors.length || !result.metafile) return;
          const manifest = finish(result.metafile, apiBase);
          console.log(`[dev] rebuilt: ${manifest["app.js"]}, ${manifest["styles.css"]}`);
        });
      },
    },
  ],
});
await ctx.watch();

const port = Number(process.env.ZIV_MOCK_PORT ?? 8787);
const mock = createMockServer({ staticDir: outdir, log: (line) => console.log(`[mock] ${line}`) });
const origin = await mock.listen(port, process.env.ZIV_MOCK_HOST ?? "127.0.0.1");
console.log(`[dev] console + mock relay at ${origin}/`);
console.log(`[dev] sign in with: admin-token (everything), send-token (send+read), read-token (read)`);
if (apiBase) console.log(`[dev] note: the console is built to call ${apiBase}, not this mock`);

const stop = async () => {
  await ctx.dispose();
  await mock.close();
  process.exit(0);
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
