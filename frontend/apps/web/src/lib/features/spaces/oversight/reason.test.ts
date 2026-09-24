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

import { REASON_MAX_LENGTH, REASON_MIN_LENGTH, normalizeReason, reasonError } from "./reason";

const FREE_TEXT = fileURLToPath(
  new URL(
    "../../../../../../../../backend/src/eneo/audit/application/free_text.py",
    import.meta.url
  )
);

describe("oversight reason", () => {
  it("uses the API's bounds", () => {
    const source = readFileSync(FREE_TEXT, "utf8");
    expect(/^REASON_MIN_LENGTH = (\d+)$/m.exec(source)?.[1]).toBe(String(REASON_MIN_LENGTH));
    expect(/^REASON_MAX_LENGTH = (\d+)$/m.exec(source)?.[1]).toBe(String(REASON_MAX_LENGTH));
  });

  it("counts the text the way the API stores it", () => {
    expect(normalizeReason("  Ärende\r\n\t 2026-114  ")).toBe("Ärende 2026-114");
    expect(normalizeReason("a\u2028b\u2029c")).toBe("a b c");
    expect(normalizeReason("ab\u200bc\u202ed\u2066e\u0007f")).toBe("abcdef");
    expect(normalizeReason("A\u030a")).toBe("Å");
  });

  it("asks for more text until ten characters remain after normalising", () => {
    expect(reasonError("")).toBe("oversight_reason_too_short(10)");
    expect(reasonError("   kort    text   ")).toBe("oversight_reason_too_short(10)");
    expect(reasonError("\u200b".repeat(20) + "123456789")).toBe("oversight_reason_too_short(10)");
    expect(reasonError("Ärende 114")).toBeNull();
  });
});
