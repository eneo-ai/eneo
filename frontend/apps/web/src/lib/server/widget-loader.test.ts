import { describe, expect, it } from "vitest";
import { readManifest, resolveLoaderVariant, type WidgetLoaderBundle } from "./widget-loader";

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

describe("readManifest", () => {
  const manifest = {
    version: "2.0.0",
    channel: "v1",
    file: "eneo.js",
    integrity: "sha384-abc",
    bytes: 100,
    gzip_bytes: 80
  };

  it("serves the channel the package records, not the major version", () => {
    expect(readManifest(JSON.stringify(manifest))).toEqual({
      version: "2.0.0",
      channel: "v1",
      integrity: "sha384-abc"
    });
  });

  it("treats a build that records no channel as not built", () => {
    expect(readManifest(JSON.stringify({ ...manifest, channel: undefined }))).toBeNull();
  });
});
