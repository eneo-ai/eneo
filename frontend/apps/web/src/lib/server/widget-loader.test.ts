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

describe("pinned loader", () => {
  it("serves the current build under its exact version and under the channel", async () => {
    const current = await getWidgetLoaderBundle();
    expect(current?.version).toBeDefined();
    expect(await getWidgetLoaderBundle(current!.version)).toEqual(current);
    expect(await getWidgetLoaderBundle(current!.channel)).toEqual(current);
    expect(`sha384-${createHash("sha384").update(current!.source).digest("base64")}`).toBe(
      current!.integrity
    );
    expect(resolveLoaderVariant(current!, current!.version)).toBe("pinned");
  });

  it("serves nothing for a version that was never released, however it is spelled", async () => {
    // A pinned request is matched against build-time paths, never used as one.
    expect(await getWidgetLoaderBundle("0.0.1")).toBeNull();
    expect(await getWidgetLoaderBundle("../dist")).toBeNull();
  });
});
