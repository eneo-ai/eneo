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
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => "sv" }));

import { modelLabel, retentionLabel } from "./labels";

describe("oversight labels", () => {
  it("names a model with where it is hosted", () => {
    expect(modelLabel({ name: "GPT-5", hosting: "eu" })).toBe("GPT-5 · hosting_eu");
    expect(modelLabel({ name: "Lokal", hosting: "on-prem" })).toBe("Lokal · on-prem");
    expect(modelLabel({ name: "Okänd" })).toBe("Okänd");
  });

  it("writes a retention as days, grouped like other numbers, or where it comes from", () => {
    const grouped = new Intl.NumberFormat("sv-SE").format(1000);
    expect(retentionLabel(1000, "inherited")).toBe(`admin_spaces_retention_days(${grouped})`);
    expect(retentionLabel(1, "inherited")).toBe("admin_spaces_retention_days_one");
    expect(retentionLabel(null, "inherited")).toBe("inherited");
    expect(retentionLabel(undefined, "inherited")).toBe("inherited");
  });
});
