import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  getWidgetLoaderBundle,
  readManifest,
  resolveLoaderVariant,
  type WidgetLoaderBundle
} from "./widget-loader";

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

  it("requires a stylesheet hash when a release has external CSS", () => {
    expect(readManifest(JSON.stringify({ ...manifest, css_file: "eneo.css" }))).toBeNull();
    expect(
      readManifest(
        JSON.stringify({ ...manifest, css_file: "eneo.css", css_integrity: "sha384-css" })
      )
    ).toEqual({
      version: "2.0.0",
      channel: "v1",
      integrity: "sha384-abc",
      cssIntegrity: "sha384-css"
    });
  });
});

describe("archived pinned loader", () => {
  it("keeps serving the exact previous release after the current loader changes", async () => {
    const old = await getWidgetLoaderBundle("1.0.3");
    expect(old?.version).toBe("1.0.3");
    expect(old?.integrity).toBe(
      "sha384-YuGHNkfFRRXBGeTXTqve526MaS696/y8Lm175OLqyf7y/6c+V1KVgIZcRstCIKOD"
    );
    expect(`sha384-${createHash("sha384").update(old!.source).digest("base64")}`).toBe(
      old?.integrity
    );
    expect(old?.cssSource).toBeUndefined();
    expect(resolveLoaderVariant(old!, "1.0.3")).toBe("pinned");
  });
});
