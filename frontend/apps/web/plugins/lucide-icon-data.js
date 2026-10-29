// @ts-check
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const moduleId = "virtual:lucide-icon-data";
const resolvedId = `\0${moduleId}`;

/**
 * Serve every Lucide icon as data from one module, `virtual:lucide-icon-data`.
 *
 * Template icons are picked by name from the whole Lucide set. Importing the
 * `@lucide/svelte` namespace for that made Vite and Rollup compile its ~3,700
 * modules (a Svelte component per icon, plus alias re-exports) in both the SSR
 * and the client build: more than the app's own source files. The picker only
 * needs the SVG nodes those components wrap, which LucideSvg.svelte draws the
 * same way. Reading them from the installed package keeps names and aliases in
 * step with the `@lucide/svelte` version the app uses.
 *
 * @returns {import("vite").Plugin}
 */
export function lucideIconData() {
  let root = process.cwd();
  /** @type {Promise<string> | undefined} */
  let code;
  return {
    name: "eneo:lucide-icon-data",
    configResolved(config) {
      root = config.root;
    },
    resolveId(id) {
      return id === moduleId ? resolvedId : null;
    },
    load(id) {
      if (id !== resolvedId) return null;
      const entry = createRequire(join(root, "package.json")).resolve("@lucide/svelte");
      // JSON.parse of a string literal parses faster than the same object literal.
      code ??= readLucideIconData(dirname(entry)).then(
        (data) => `export default JSON.parse(${JSON.stringify(JSON.stringify(data))});`
      );
      return code;
    }
  };
}

/**
 * @typedef {import("@lucide/svelte").IconNode} IconNode
 * @typedef {{
 *   icons: Record<string, [name: string, node: IconNode]>,
 *   aliases: Record<string, string>
 * }} LucideIconData
 */

/**
 * Read the icon set from an installed `@lucide/svelte`'s `dist` directory.
 *
 * `icons` maps each current export name (`House`) to Lucide's own icon name
 * (`house`, the `lucide-house` class) and its SVG nodes; `aliases` maps
 * renamed icons' old export names (`Home`) to the current one. The package
 * also exports every icon and alias as `Lucide<Name>` and `<Name>Icon`;
 * that rule is checked here, not listed, and lucideIcons.ts applies it.
 *
 * Throws when the files do not have the shape parsed here, so a Lucide
 * upgrade that changes them fails the build instead of losing icons.
 *
 * @param {string} dist
 * @param {(path: string) => Promise<string>} read
 * @returns {Promise<LucideIconData>}
 */
export async function readLucideIconData(dist, read = (path) => readFile(path, "utf8")) {
  const index = await read(join(dist, "icons/index.js"));
  const exports = [
    ...index.matchAll(/export \{ default as (\w+) \} from '\.\/([\w-]+)\.svelte';/g)
  ];
  if (exports.length === 0) throw new Error(`No icon exports found in ${dist}/icons/index.js`);

  /** @type {Map<string, string>} */
  const exportByFile = new Map(exports.map(([, exportName, file]) => [file, exportName]));
  const entries = await Promise.all(
    exports.map(async ([, exportName, file]) => {
      const source = await read(join(dist, "icons", `${file}.svelte`));
      const node = source.match(/const iconNode = (\[.*\]);\n/)?.[1];
      const name = source.match(/<Icon name="([\w-]+)"/)?.[1];
      if (!node || !name) throw new Error(`Unexpected icon source in ${dist}/icons/${file}.svelte`);
      return /** @type {[string, [string, IconNode]]} */ ([exportName, [name, JSON.parse(node)]]);
    })
  );
  // Sorted so the generated module, and the chunk hash, are the same on every build.
  const icons = Object.fromEntries(entries.sort(([a], [b]) => (a < b ? -1 : 1)));

  /** The current export name behind an `icons/<file>.js` re-export. */
  const resolveFile = async (/** @type {string} */ file) => {
    const source = await read(join(dist, "icons", `${file}.js`));
    const target = source.match(/export \{ default \} from "\.\/([\w-]+)\.svelte";/)?.[1];
    const exportName = target && exportByFile.get(target);
    if (!exportName) throw new Error(`Cannot resolve ${dist}/icons/${file}.js to an icon`);
    return exportName;
  };
  /**
   * Export names and the icon each points to, from an `aliases/*.js` file.
   * @param {string} file
   * @returns {Promise<[string, string][]>}
   */
  const readAliases = async (file) => {
    const source = await read(join(dist, "aliases", file));
    const reexports = [
      ...source.matchAll(/default as (\w+) \} from '\.\.\/icons\/([\w-]+)\.js';/g)
    ];
    return Promise.all(
      reexports.map(async ([, alias, target]) => [alias, await resolveFile(target)])
    );
  };

  const aliasEntries = await readAliases("aliases.js");
  if (aliasEntries.length === 0) throw new Error(`No aliases found in ${dist}/aliases/aliases.js`);
  const aliases = Object.fromEntries(aliasEntries.sort(([a], [b]) => (a < b ? -1 : 1)));

  const current = new Map([
    ...Object.keys(icons).map((name) => /** @type {const} */ ([name, name])),
    ...Object.entries(aliases)
  ]);
  for (const [file, prefix, suffix] of [
    ["prefixed.js", "Lucide", ""],
    ["suffixed.js", "", "Icon"]
  ]) {
    const actual = new Map(await readAliases(file));
    const expected = [...current].map(([name, icon]) => [`${prefix}${name}${suffix}`, icon]);
    if (
      actual.size !== expected.length ||
      expected.some(([name, icon]) => actual.get(name) !== icon)
    )
      throw new Error(`${dist}/aliases/${file} no longer follows ${prefix}<Name>${suffix}`);
  }

  return { icons, aliases };
}
