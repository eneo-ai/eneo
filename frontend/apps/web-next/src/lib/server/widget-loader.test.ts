import { afterEach, describe, expect, it, vi } from "vitest";

const files = vi.hoisted(() => new Map<string, string>());
vi.mock("node:fs/promises", () => ({
  readFile: async (file: string) => {
    for (const [suffix, content] of files) if (file.endsWith(suffix)) return content;
    throw Object.assign(new Error(`ENOENT: ${file}`), { code: "ENOENT" });
  }
}));

import { loaderAssetResponse, readManifest, resolveLoaderVariant } from "./widget-loader";

const current = {
  version: "1.0.11",
  channel: "v1",
  file: "eneo.js",
  integrity: "sha384-current",
  bytes: 1,
  gzip_bytes: 1,
  css_file: "eneo.css",
  css_integrity: "sha384-current-css",
  css_bytes: 1
};
const archived = {
  ...current,
  version: "1.0.10",
  integrity: "sha384-old",
  css_integrity: "sha384-old-css"
};

function build() {
  files.set("dist/manifest.json", JSON.stringify(current));
  files.set("dist/eneo.js", "current();");
  files.set("dist/eneo.css", ".current{}");
  files.set("releases/1.0.10/manifest.json", JSON.stringify(archived));
  files.set("releases/1.0.10/eneo.js", "old();");
  files.set("releases/1.0.10/eneo.css", ".old{}");
}

afterEach(() => files.clear());

describe("readManifest", () => {
  it("accepts the package's manifest and refuses one that names another file", () => {
    expect(readManifest(JSON.stringify(current))).toEqual({
      version: "1.0.11",
      channel: "v1",
      integrity: "sha384-current",
      cssIntegrity: "sha384-current-css"
    });
    expect(readManifest(JSON.stringify({ ...current, file: "evil.js" }))).toBeNull();
    expect(readManifest(JSON.stringify({ ...current, css_file: "x.css" }))).toBeNull();
  });
});

describe("loaderAssetResponse", () => {
  it("answers 503 until the package is built", async () => {
    const response = await loaderAssetResponse(
      new Request("http://x/widget/v1/eneo.js"),
      "v1",
      "js"
    );
    expect(response.status).toBe(503);
    expect(response.headers.get("retry-after")).toBe("60");
  });

  it("serves the channel from the current build, cacheable for an hour, open to every origin", async () => {
    build();
    const response = await loaderAssetResponse(
      new Request("http://x/widget/v1/eneo.js"),
      "v1",
      "js"
    );
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("current();");
    expect(response.headers.get("content-type")).toBe("text/javascript; charset=utf-8");
    expect(response.headers.get("cache-control")).toBe("public, max-age=3600");
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    expect(response.headers.get("x-eneo-widget-version")).toBe("1.0.11");
    expect(response.headers.get("etag")).toBe('"sha384-current"');
  });

  it("serves a pinned release immutably, with its own stylesheet, and answers 304 to its ETag", async () => {
    build();
    const js = await loaderAssetResponse(
      new Request("http://x/widget/1.0.10/eneo.js"),
      "1.0.10",
      "js"
    );
    expect(await js.text()).toBe("old();");
    expect(js.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");
    const css = await loaderAssetResponse(
      new Request("http://x/widget/1.0.10/eneo.css"),
      "1.0.10",
      "css"
    );
    expect(await css.text()).toBe(".old{}");
    expect(css.headers.get("content-type")).toBe("text/css; charset=utf-8");
    const cached = await loaderAssetResponse(
      new Request("http://x/widget/1.0.10/eneo.js", {
        headers: { "if-none-match": '"sha384-old"' }
      }),
      "1.0.10",
      "js"
    );
    expect(cached.status).toBe(304);
  });

  it("knows no version it has not got, and never reads a path from the request", async () => {
    build();
    for (const version of ["1.0.9", "../dist", "v2", "1.0.10/../1.0.10"]) {
      const response = await loaderAssetResponse(
        new Request("http://x/widget/x/eneo.js"),
        version,
        "js"
      );
      expect(response.status, version).toBe(404);
    }
    expect(resolveLoaderVariant({ ...current, source: "" }, "v1")).toBe("channel");
    expect(resolveLoaderVariant({ ...current, source: "" }, "1.0.11")).toBe("pinned");
    expect(resolveLoaderVariant({ ...current, source: "" }, "1.0.10")).toBeNull();
  });
});
