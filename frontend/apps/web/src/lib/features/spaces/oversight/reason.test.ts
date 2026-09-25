import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));

import {
  REASON_MAX_LENGTH,
  REASON_MIN_LENGTH,
  normalizeReason,
  reasonError,
  reasonLength,
  visibleLength
} from "./reason";

const FREE_TEXT = readFileSync(
  fileURLToPath(
    new URL(
      "../../../../../../../../backend/src/eneo/audit/application/free_text.py",
      import.meta.url
    )
  ),
  "utf8"
);

/** The characters of a Python string literal's body, with `a-b` ranges expanded. */
function pythonCharacterSet(body: string): string[] {
  const units = [
    ...body.matchAll(/\\x([0-9a-f]{2})|\\u([0-9a-f]{4})|\\([tnvfr])|(-)|([^\\])/giu)
  ].map(([, hex, unicode, escape, dash, plain]) => {
    if (hex || unicode) return String.fromCodePoint(parseInt(hex ?? unicode, 16));
    if (escape) return { t: "\t", n: "\n", v: "\v", f: "\f", r: "\r" }[escape]!;
    return dash ? { range: true } : plain;
  });
  const chars: string[] = [];
  for (let i = 0; i < units.length; i++) {
    const unit = units[i];
    if (typeof unit === "string") {
      chars.push(unit);
      continue;
    }
    const from = chars.pop()!.codePointAt(0)!;
    const to = (units[++i] as string).codePointAt(0)!;
    for (let code = from; code <= to; code++) chars.push(String.fromCodePoint(code));
  }
  return chars;
}

const WHITESPACE = pythonCharacterSet(/^_WHITESPACE = "(.*)"$/m.exec(FREE_TEXT)![1]);
const IGNORABLE_RANGES = [
  .../^_DEFAULT_IGNORABLE = \(([\s\S]*?)^\)/m
    .exec(FREE_TEXT)![1]
    .matchAll(/\((0x[0-9A-F]+), (0x[0-9A-F]+)\)/g)
].map(([, low, high]) => [Number(low), Number(high)] as const);

describe("oversight reason", () => {
  it("uses the API's bounds", () => {
    expect(/^REASON_MIN_LENGTH = (\d+)$/m.exec(FREE_TEXT)?.[1]).toBe(String(REASON_MIN_LENGTH));
    expect(/^REASON_MAX_LENGTH = (\d+)$/m.exec(FREE_TEXT)?.[1]).toBe(String(REASON_MAX_LENGTH));
  });

  it("collapses exactly the API's whitespace into one space", () => {
    expect(WHITESPACE).toContain("\u0085");
    expect(WHITESPACE).toContain("\u3000");
    for (const char of WHITESPACE) {
      const code = char.codePointAt(0)!.toString(16);
      expect(normalizeReason(`a${char}${char}b`), code).toBe("a b");
    }
    // In JS `\s` but not Unicode White_Space: removed like every format character.
    expect(normalizeReason("a\ufeffb")).toBe("ab");
  });

  it("removes every default-ignorable code point the API removes", () => {
    expect(IGNORABLE_RANGES.length).toBeGreaterThan(10);
    for (const [low, high] of IGNORABLE_RANGES) {
      for (const code of new Set([low, (low + high) >> 1, high])) {
        expect(normalizeReason(`a${String.fromCodePoint(code)}b`), code.toString(16)).toBe("ab");
      }
    }
  });

  it("stores the text the way the API does", () => {
    expect(normalizeReason("  Ärende\r\n\t 2026-114  ")).toBe("Ärende 2026-114");
    expect(normalizeReason("a\u2028b\u2029c")).toBe("a b c");
    expect(normalizeReason("ab\u200bc\u202ed\u2066e\u0007f")).toBe("abcdef");
    expect(normalizeReason("A\u030a")).toBe("Å");
    // U+001C is a control character here, not whitespace as in Python's isspace().
    expect(normalizeReason("abcd\x1cefghi")).toBe("abcdefghi");
    expect(normalizeReason("abcd\x85efghij")).toBe("abcd efghij");
    // Removed before composing, so nothing composes across a removed character.
    expect(normalizeReason("abcdefgh" + "e\u200b\u0301")).toBe("abcdefghé");
  });

  it("normalises idempotently", () => {
    const samples = [
      "  a\u200b\u0301 b\u0085\u00a0c\ufeff ",
      "e\u2060\u0301\u0323 \u1100\u1161\u11a8",
      "\u{1F44D}\u{1F3FD}\u{E0041}\u2800x\ufe0f",
      "\ud800abc\udfff",
      "abcdefgh" + "e\u200b\u0301"
    ];
    for (const sample of samples) {
      const once = normalizeReason(sample);
      expect(normalizeReason(once), JSON.stringify(sample)).toBe(once);
    }
  });

  it("counts visible characters, not code units or marks", () => {
    expect(visibleLength("\u{1F600}".repeat(5))).toBe(5);
    expect(visibleLength("e\u0301 e\u0301")).toBe(2);
    expect(reasonLength("  kort\u00a0\u00a0 text  ")).toBe(9);
    expect(reasonLength("\u{1F600}".repeat(3))).toBe(3);
  });

  it("asks for ten visible characters after normalising", () => {
    const tooShort = "oversight_reason_too_short(10)";
    expect(reasonError("")).toBe(tooShort);
    expect(reasonError("   kort    text   ")).toBe(tooShort);
    expect(reasonError("\u200b".repeat(20) + "123456789")).toBe(tooShort);
    expect(reasonError("abcdefgh" + "e\u200b\u0301")).toBe(tooShort);
    expect(reasonError("abcd\x1cefghi")).toBe(tooShort);
    for (const invisible of ["\u2060", "\ufeff", "\u00ad", "\u3164", "\u2800"]) {
      expect(reasonError(invisible.repeat(10)), invisible).toBe(tooShort);
    }
    expect(reasonError("\u{1F600}".repeat(5))).toBe(tooShort);
    expect(reasonError("\u{1F600}".repeat(10))).toBeNull();
    // Spaces are not visible characters.
    expect(reasonError("Ärende 114")).toBe(tooShort);
    expect(reasonError("abcd\x85efghij")).toBeNull();
    expect(reasonError("Ärende 2026-114")).toBeNull();
  });

  it("allows 500 characters, counted as code points", () => {
    expect(reasonError("a".repeat(REASON_MAX_LENGTH))).toBeNull();
    // 1000 UTF-16 units, 500 code points.
    expect(reasonError("\u{1F600}".repeat(REASON_MAX_LENGTH))).toBeNull();
    expect(reasonError("a".repeat(REASON_MAX_LENGTH + 1))).toBe("oversight_reason_too_long(500)");
  });
});
