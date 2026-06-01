import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  getTemplateIconComponent,
  isTemplateIconName,
  normalizeTemplateIconName,
  templateIconOptions
} from "./templateIconRegistry";

const sourceRoot = fileURLToPath(new URL("../../..", import.meta.url));
const sourceExtensions = new Set([".svelte", ".ts"]);
const forbiddenLucidePatterns = [
  /import\s+\*\s+as\s+\w+\s+from\s+["']lucide-svelte["']/,
  /Object\.keys\(\s*\w*Lucide\w*\s*\)/,
  /\w*Lucide\w*\s*(?:as\s+Record<[^>]+>)?\s*\[[^\]]+\]/
];

function listSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    const stats = statSync(path);

    if (stats.isDirectory()) {
      if (entry === "paraglide") {
        return [];
      }
      return listSourceFiles(path);
    }

    if (entry.endsWith(".test.ts")) {
      return [];
    }

    if (![...sourceExtensions].some((extension) => entry.endsWith(extension))) {
      return [];
    }

    return [path];
  });
}

describe("templateIconRegistry", () => {
  it("normalizes stored and UI icon names to one value shape", () => {
    expect(normalizeTemplateIconName("MessageSquare")).toBe("message-square");
    expect(normalizeTemplateIconName("message_square")).toBe("message-square");
    expect(normalizeTemplateIconName(" message square ")).toBe("message-square");
    expect(normalizeTemplateIconName("message-square")).toBe("message-square");
  });

  it("resolves supported icons and safely ignores unsupported persisted values", () => {
    expect(getTemplateIconComponent("message-square")).toBe(
      getTemplateIconComponent("MessageSquare")
    );
    expect(getTemplateIconComponent("does-not-exist")).toBeNull();
    expect(getTemplateIconComponent(null)).toBeNull();
    expect(getTemplateIconComponent(undefined)).toBeNull();
  });

  it("exposes a type guard for canonical persisted icon names", () => {
    expect(isTemplateIconName("message-square")).toBe(true);
    expect(isTemplateIconName("MessageSquare")).toBe(false);
    expect(isTemplateIconName("does-not-exist")).toBe(false);
  });

  it("keeps the curated registry unique and bounded", () => {
    const values = templateIconOptions.map((option) => option.value);
    const uniqueValues = new Set(values);

    expect(uniqueValues.size).toBe(values.length);
    expect(values.every((value) => /^[a-z][a-z0-9-]*$/.test(value))).toBe(true);
    expect(values.length).toBeGreaterThanOrEqual(40);
    expect(values.length).toBeLessThanOrEqual(80);
  });

  it("keeps lucide-svelte namespace imports out of app source", () => {
    const violations = listSourceFiles(sourceRoot).flatMap((path) => {
      const source = readFileSync(path, "utf8");

      return forbiddenLucidePatterns
        .filter((pattern) => pattern.test(source))
        .map((pattern) => ({
          file: relative(sourceRoot, path),
          pattern: pattern.source
        }));
    });

    expect(
      violations,
      "Use named lucide-svelte imports in app source; do not import or enumerate the full icon module."
    ).toEqual([]);
  });
});
