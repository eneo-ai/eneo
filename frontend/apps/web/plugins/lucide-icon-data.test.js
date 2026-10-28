import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { lucideIconData, readLucideIconData } from "./lucide-icon-data.js";

const dist = dirname(fileURLToPath(import.meta.resolve("@lucide/svelte")));

test("reads every icon of the installed @lucide/svelte, with its aliases", async () => {
  const { icons, aliases } = await readLucideIconData(dist);
  const components = (await readdir(join(dist, "icons"))).filter((f) => f.endsWith(".svelte"));

  assert.equal(Object.keys(icons).length, components.length);
  const [name, node] = icons.Rocket;
  assert.equal(name, "rocket");
  const source = await readFile(join(dist, "icons/rocket.svelte"), "utf8");
  assert.ok(node.length > 0);
  for (const [tag, attrs] of node) {
    assert.ok(source.includes(`["${tag}", {`));
    for (const value of Object.values(attrs)) assert.ok(source.includes(`"${value}"`));
  }
  assert.equal(aliases.Home, "House");
  for (const icon of Object.values(aliases)) assert.ok(icons[icon], `${icon} is a current icon`);
});

test("serves the icon set as one module", async () => {
  const plugin = /** @type {any} */ (lucideIconData());
  plugin.configResolved({ root: fileURLToPath(new URL("..", import.meta.url)) });
  const id = plugin.resolveId("virtual:lucide-icon-data");
  const code = await plugin.load(id);

  const module = await import(`data:text/javascript,${encodeURIComponent(code)}`);
  assert.deepEqual(module.default, await readLucideIconData(dist));
});

/** Reads the installed package, with `edit` applied to the file ending in `suffix`. */
const tampered =
  (/** @type {string} */ suffix, /** @type {(source: string) => string} */ edit) =>
  async (/** @type {string} */ path) => {
    const source = await readFile(path, "utf8");
    return path.endsWith(suffix) ? edit(source) : source;
  };

test("fails when an icon no longer has the expected source", async () => {
  const read = tampered("icons/rocket.svelte", (s) => s.replace("const iconNode", "let iconNode"));
  await assert.rejects(readLucideIconData(dist, read), /icons\/rocket\.svelte/);
});

test("fails when an alias no longer resolves to an icon", async () => {
  const read = tampered("icons/home.js", (s) =>
    s.replace("./house.svelte", "./no-such-icon.svelte")
  );
  await assert.rejects(readLucideIconData(dist, read), /icons\/home\.js/);
});

test("fails when the Lucide<Name> exports stop following the rule", async () => {
  const read = tampered("aliases/prefixed.js", (s) =>
    s.replace("as LucideRocket ", "as LucideRocketShip ")
  );
  await assert.rejects(readLucideIconData(dist, read), /prefixed\.js/);
});
