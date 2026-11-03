import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { LUCIDE_ALIASES } from "./lucide-aliases";
import { TEMPLATE_ICON_NAMES, storedTemplateIconName, templateIconName } from "./template-icon";

/** Lucide's export name for an icon name (its own toPascalCase). */
const lucidePascal = (name: string) =>
  name.replace(/(^|-)(\w)/g, (_match, _dash, letter: string) => letter.toUpperCase());
/** How the Svelte reader (apps/web lucideIcons.ts toPascalCase) turns a stored name back. */
const sveltePascal = (name: string) =>
  name.charAt(0).toUpperCase() + name.slice(1).replace(/-([a-z])/g, (g) => g[1]!.toUpperCase());

/** Each name in the installed lucide-react/dynamic and the icon file its import loads. */
function installedIconFiles(): Map<string, string> {
  const root = path.dirname(createRequire(import.meta.url).resolve("lucide-react/package.json"));
  const source = readFileSync(path.join(root, "dist/esm/dynamicIconImports.mjs"), "utf8");
  return new Map(
    [...source.matchAll(/^ {2}"([^"]+)": \(\) => import\('\.\/icons\/([^']+)\.mjs'\)/gm)].map(
      ([, name, file]) => [name!, file!]
    )
  );
}

describe("template icon names", () => {
  it("finds a stored icon name however it is written, and nothing for an unknown one", () => {
    expect(templateIconName("message-square")).toBe("message-square");
    expect(templateIconName("MessageSquare")).toBe("message-square");
    // The Svelte picker stored `ArrowDown01` as `arrow-down01`.
    expect(templateIconName("arrow-down01")).toBe("arrow-down-0-1");
    // An old name Lucide keeps for a renamed icon reads as the current one.
    expect(templateIconName("home")).toBe("house");
    expect(templateIconName("no-such-icon")).toBeNull();
    expect(templateIconName(null)).toBeNull();
    expect(templateIconName("")).toBeNull();
  });

  it("knows Lucide's old names as the installed lucide-react maps them", () => {
    const files = installedIconFiles();
    expect(files.size).toBeGreaterThan(1000);
    const aliases = Object.fromEntries([...files].filter(([name, file]) => name !== file));
    // On a lucide-react upgrade, copy the received map into lucide-aliases.ts.
    expect(LUCIDE_ALIASES).toEqual(aliases);
  });

  it("offers each icon once, under its current name", () => {
    const files = installedIconFiles();
    const offered = TEMPLATE_ICON_NAMES.map((name) => files.get(name));
    expect(new Set(offered).size).toBe(TEMPLATE_ICON_NAMES.length);
    expect(new Set(offered)).toEqual(new Set(files.values()));
    for (const name of TEMPLATE_ICON_NAMES) expect(files.get(name), name).toBe(name);
  });

  // The Svelte reader's rule, not its registry: web-next cannot depend on the
  // Svelte app, whose older Lucide lacks the newest icons.
  it("stores a picked icon in a form both readers turn back into its Lucide name", () => {
    expect(storedTemplateIconName("calendar-check-2")).toBe("calendar-check2");
    expect(storedTemplateIconName("arrow-down-0-1")).toBe("arrow-down01");
    expect(storedTemplateIconName("a-arrow-down")).toBe("a-arrow-down");
    for (const name of TEMPLATE_ICON_NAMES) {
      const stored = storedTemplateIconName(name);
      expect(sveltePascal(stored), name).toBe(lucidePascal(name));
      expect(templateIconName(stored), name).toBe(name);
    }
  });
});
