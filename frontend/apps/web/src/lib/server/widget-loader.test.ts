import { describe, expect, it } from "vitest";
import { resolveLoaderVariant, type WidgetLoaderBundle } from "./widget-loader";

const bundle: WidgetLoaderBundle = {
  version: "1.4.2",
  channel: "v1",
  integrity: "sha384-abc",
  source: "!function(){}();"
};

describe("resolveLoaderVariant", () => {
  it("serves the floating channel and the exact pinned version only", () => {
    expect(resolveLoaderVariant(bundle, "v1")).toBe("channel");
    expect(resolveLoaderVariant(bundle, "1.4.2")).toBe("pinned");
    expect(resolveLoaderVariant(bundle, "v2")).toBeNull();
    expect(resolveLoaderVariant(bundle, "1.4.1")).toBeNull();
    expect(resolveLoaderVariant(bundle, "latest")).toBeNull();
    expect(resolveLoaderVariant(bundle, "")).toBeNull();
  });
});
