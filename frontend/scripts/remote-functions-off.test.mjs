import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// audit-dependencies.mjs accepts GHSA-3r8g-jcqq-3p5j because only remote
// functions parse the affected form data. This keeps that reason true by
// reading kit.experimental.remoteFunctions from the config a production build
// resolves: SvelteKit's setup plugin carries it, taken from svelte.config.js
// or, when options are passed to sveltekit() in the Vite config, from those
// options alone. This is SvelteKit's own lookup (load_config_from_vite in
// @sveltejs/kit/src/core/config) without its fallback to svelte.config.js.
// Resolving the config in build mode regenerates the project's .svelte-kit.
const frontend = fileURLToPath(new URL("..", import.meta.url));
const OFF = 0;
const ON = 3;
const resolve = `
const { resolveConfig } = await import("vite");
const config = await resolveConfig({}, "build", "production");
const setup = config.plugins.find(
  (plugin) => plugin.name === "vite-plugin-sveltekit-setup" && plugin.api?.options,
);
const flag = setup?.api.options.kit?.experimental?.remoteFunctions;
if (typeof flag !== "boolean")
  throw new Error("No SvelteKit setup plugin with kit.experimental.remoteFunctions in the resolved Vite config.");
process.exit(flag ? ${ON} : ${OFF});
`;

// One process per project, started in the project as `vite build` is: Vite
// resolves from there, and SvelteKit keeps the working directory in module
// state. Anything but the two agreed exit codes fails.
function remoteFunctions(project) {
  const result = spawnSync(
    process.execPath,
    ["--input-type=module", "--eval", resolve],
    {
      cwd: project,
      env: { ...process.env, NODE_ENV: "production" },
      encoding: "utf8",
      timeout: 120_000,
    },
  );
  if (result.status === OFF) return false;
  if (result.status === ON) return true;
  throw new Error(
    `Could not read kit.experimental.remoteFunctions from the Vite config in ${project} (status ${result.status}, signal ${result.signal}):\n${result.stderr}`,
  );
}

// A throwaway SvelteKit project under the web app's node_modules, so its Vite
// config resolves the installed SvelteKit and Vite.
function fixture(t, svelteConfig, plugins) {
  const parent = join(frontend, "apps/web/node_modules/.cache");
  mkdirSync(parent, { recursive: true });
  const dir = mkdtempSync(join(parent, "remote-functions-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  mkdirSync(join(dir, "src"));
  writeFileSync(
    join(dir, "src/app.html"),
    "<html><head>%sveltekit.head%</head><body>%sveltekit.body%</body></html>\n",
  );
  writeFileSync(join(dir, "package.json"), '{ "type": "module" }\n');
  writeFileSync(
    join(dir, "svelte.config.js"),
    `export default ${svelteConfig};\n`,
  );
  writeFileSync(
    join(dir, "vite.config.js"),
    `import { sveltekit } from "@sveltejs/kit/vite";\nexport default { plugins: [${plugins}] };\n`,
  );
  return dir;
}

const flagOn = "{ kit: { experimental: { remoteFunctions: true } } }";

test("the web app and the component library build with remote functions off", () => {
  for (const project of ["apps/web", "packages/ui"])
    assert.equal(remoteFunctions(join(frontend, project)), false, project);
});

test("the flag is found when svelte.config.js turns it on", (t) => {
  assert.equal(remoteFunctions(fixture(t, flagOn, "sveltekit()")), true);
});

test("the flag is found when options passed to sveltekit() turn it on", (t) => {
  const plugin = "sveltekit({ experimental: { remoteFunctions: true } })";
  assert.equal(remoteFunctions(fixture(t, "{}", plugin)), true);
});

test("options passed to sveltekit() replace svelte.config.js", (t) => {
  assert.equal(remoteFunctions(fixture(t, flagOn, "sveltekit({})")), false);
});

test("a Vite config without SvelteKit fails instead of passing", (t) => {
  assert.throws(
    () => remoteFunctions(fixture(t, flagOn, "")),
    /No SvelteKit setup plugin/,
  );
});
