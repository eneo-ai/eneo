import { describe, expect, it, vi } from "vitest";

const locale = vi.hoisted(() => ({ current: "sv" }));
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => locale.current }));

import { formatList } from "./formatList";

describe("formatList", () => {
  it("joins names the way the UI language does", () => {
    locale.current = "sv";
    expect(formatList(["Ada", "Bo", "Cecilia"])).toBe("Ada, Bo och Cecilia");
    locale.current = "en";
    expect(formatList(["Ada", "Bo", "Cecilia"])).toBe("Ada, Bo, and Cecilia");
    expect(formatList(["Ada"])).toBe("Ada");
    expect(formatList([])).toBe("");
  });
});
