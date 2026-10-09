import { afterEach, describe, expect, it, vi } from "vitest";

const locale = vi.hoisted(() => ({ current: "en" }));
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => locale.current }));

import { formatList } from "./formatList";

afterEach(() => {
  locale.current = "en";
});

describe("formatList", () => {
  it("returns an empty string for no items and the item itself for one", () => {
    expect(formatList([])).toBe("");
    expect(formatList(["Sammanfatta"])).toBe("Sammanfatta");
  });

  it("joins items with the UI language's conjunction", () => {
    expect(formatList(["A", "B", "C"])).toBe("A, B, and C");
    locale.current = "sv";
    expect(formatList(["A", "B"])).toBe("A och B");
    expect(formatList(["A", "B", "C"])).toBe("A, B och C");
  });

  it("joins items with the UI language's disjunction when asked", () => {
    expect(formatList(["A", "B", "C"], "disjunction")).toBe("A, B, or C");
    locale.current = "sv";
    expect(formatList(["A", "B", "C"], "disjunction")).toBe("A, B eller C");
  });
});
