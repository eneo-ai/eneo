import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const appDir = path.resolve(import.meta.dirname, "../..");
const srcDir = path.join(appDir, "src");

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return sources(file);
    return /\.(tsx?|css)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [file] : [];
  });
}

/** Where a pattern occurs in the app's own source (tests excluded), with the matched text. */
function matches(pattern: RegExp): { at: string; file: string; text: string }[] {
  return sources(srcDir).flatMap((file) => {
    const source = readFileSync(file, "utf8");
    return [...source.matchAll(pattern)].map((match) => ({
      at: `${path.relative(appDir, file)}:${source.slice(0, match.index).split("\n").length}`,
      file: path.relative(appDir, file),
      text: match[0]
    }));
  });
}

/** Where a pattern occurs in the app's own source (tests excluded), as `path:line`. */
function occurrences(pattern: RegExp): string[] {
  return matches(pattern).map(({ at }) => at);
}

/**
 * Text dimmed with opacity or an alpha colour is a colour pair the token contrast
 * test (src/theme/eneo-theme.contrast.test.ts) cannot see (ACCESSIBILITY.md → Colour
 * and contrast). The uses that stay, as `file text` → why; each entry covers one use, so
 * a second one in the same file needs its own reason.
 */
const DIMMED_TEXT_ALLOWED: Record<string, string> = {
  "src/features/admin/storage/storage-admin-page.tsx opacity-60":
    "an unavailable storage target: its radio is disabled, and text of an inactive control is exempt (1.4.3)",
  "src/features/help-assistants/prompt-guide/prompt-guide-dialog.tsx opacity-60":
    "a submitted question card while it sends: its fieldset is disabled and the card aria-busy",
  "src/features/admin/audit/audit-page.tsx opacity-60":
    "a known 1.4.3 gap, not an exemption: the previous page of the audit log is dimmed while the next page loads",
  "src/components/ui/alert.tsx text-destructive/90":
    "the error alert's description: 90% of the error colour on the card is 5.6:1 light, 6.0:1 dark"
};

/** Matches that are neither allowed nor hidden behind a disabled state, and allowances never used. */
function dimmedText(pattern: RegExp, kind: RegExp) {
  const found = matches(pattern).filter(({ text }) => !/disabled/.test(text));
  const key = ({ file, text }: { file: string; text: string }) =>
    `${file} ${text.slice(text.search(kind))}`;
  const used = new Set<string>();
  return {
    unexplained: found
      .filter((hit) => {
        const entry = key(hit);
        const allowed = entry in DIMMED_TEXT_ALLOWED && !used.has(entry);
        used.add(entry);
        return !allowed;
      })
      .map(({ at, text }) => `${at} ${text}`),
    unused: Object.keys(DIMMED_TEXT_ALLOWED).filter(
      (entry) => kind.test(entry.split(" ")[1]!) && !used.has(entry)
    )
  };
}

/**
 * Source-level guards for criteria no screen walk can reach: something the app must never do,
 * which one line of source would break (ACCESSIBILITY.md, WCAG 2.2 A/AA).
 */
describe("accessibility source guards", () => {
  it("never locks the screen's orientation (1.3.4)", () => {
    const manifest = JSON.parse(readFileSync(path.join(appDir, "public/manifest.json"), "utf8"));
    expect(manifest).not.toHaveProperty("orientation");
    expect(occurrences(/screen\.orientation\.lock|@media[^{]*\(\s*orientation/g)).toEqual([]);
  });

  it("never starts audio or video by itself (1.4.2)", () => {
    expect(occurrences(/\bautoPlay\b|\bautoplay\b/g)).toEqual([]);
  });

  it("opens no menu on press, only on release (2.5.2)", () => {
    // The legacy Radix DropdownMenu opened on pointerdown, so a finger that slid off could not
    // cancel; Astryx menus open on click.
    expect(
      occurrences(/components\/ui\/dropdown-menu["']|\bDropdownMenu as \w+ } from "radix-ui"/g)
    ).toEqual([]);
  });

  it("never takes the browser's own paste or copy of a password away (3.3.8)", () => {
    // A password field that refuses paste locks out a password manager.
    expect(
      occurrences(/type=["']password["'][^>]*\bonPaste\b|\bonPaste\b[^>]*type=["']password["']/g)
    ).toEqual([]);
  });

  it("never dims text with opacity (1.4.3)", () => {
    // A class with opacity-5…95 or opacity-[…] (opacity-0 hides, opacity-100 restores),
    // and an inline or CSS opacity between 0 and 1. A variant naming a disabled state is
    // fine: text of an inactive control is exempt.
    const { unexplained, unused } = dimmedText(
      /[^\s"'`{}]*\bopacity-(?:\[[^\]]+\]|(?!0\b|100\b)\d+\b)|\bopacity:\s*0?\.\d+/g,
      /opacity/
    );
    expect(unexplained).toEqual([]);
    expect(unused).toEqual([]);
  });

  it("never gives a text colour utility an alpha (1.4.3)", () => {
    // text-sm/6 is a size with its line height, not a colour.
    const { unexplained, unused } = dimmedText(
      /[^\s"'`{}]*\btext-(?!(?:xs|sm|base|lg|\d*xl)\/)[a-z][\w-]*\/(\d+|\[[^\]]+\])/g,
      /text-/
    );
    expect(unexplained).toEqual([]);
    expect(unused).toEqual([]);
  });
});
