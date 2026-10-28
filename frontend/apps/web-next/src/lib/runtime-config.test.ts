import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Schema } from "./api/models";

const config: Schema<"WebRuntimeConfig"> = {
  version: "1.0.0",
  revision: "test-revision",
  help_center_url: null,
  legacy_app_url: null,
  accessibility_statement_url: null,
  request_integration_form_url: null,
  mcp_app_content_origin: null,
  federation_enabled: false
};

beforeEach(() => vi.resetModules());
afterEach(() => vi.unstubAllGlobals());

it("has no runtime config before boot and returns the loaded contract after initialization", async () => {
  const { runtimeConfig, setRuntimeConfig, loadRuntimeConfig } = await import("./runtime-config");
  expect(runtimeConfig).toThrow(/boot/i);
  const fetch = vi.fn().mockResolvedValue(Response.json(config));
  vi.stubGlobal("fetch", fetch);
  const loaded = await loadRuntimeConfig();
  expect(fetch).toHaveBeenCalledWith("/api/v1/runtime-config", {
    credentials: "same-origin",
    cache: "no-store"
  });
  setRuntimeConfig(loaded);
  expect(runtimeConfig()).toEqual(config);
});

it("rejects a failed request without exposing its response body", async () => {
  const { loadRuntimeConfig } = await import("./runtime-config");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("internal failure", { status: 500 }))
  );
  await expect(loadRuntimeConfig()).rejects.toThrow("500");
  await expect(loadRuntimeConfig()).rejects.not.toThrow("internal failure");
});

it("rejects a response that cannot be decoded as JSON", async () => {
  const { loadRuntimeConfig } = await import("./runtime-config");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>Unavailable</html>")));
  await expect(loadRuntimeConfig()).rejects.toThrow();
});
