import type { ConfigEnv, ProxyOptions, UserConfig, UserConfigFnObject } from "vite";
import { afterEach, describe, expect, it, vi } from "vitest";
import viteConfig from "../vite.config.mjs";

const serve: ConfigEnv = { command: "serve", mode: "development" };

function config(env: ConfigEnv): UserConfig {
  return (viteConfig as UserConfigFnObject)(env);
}

// Vite's matcher: a key starting with ^ is a RegExp over the path and query.
function proxiedBy(url: string): ProxyOptions | undefined {
  const proxy = config(serve).server?.proxy ?? {};
  const key = Object.keys(proxy).find((context) => new RegExp(context).test(url));
  return key === undefined ? undefined : (proxy[key] as ProxyOptions);
}

describe("dev server proxy", () => {
  afterEach(() => vi.unstubAllEnvs());

  it.each([
    "/api",
    "/api/v1/runtime-config",
    "/api/v1/spaces/?page=2",
    "/api?x=1",
    "/version",
    "/login/callback?code=c&state=s",
    "/auth/callback",
    "/auth/callback/"
  ])("sends %s to the backend with the browser's Host", (url) => {
    vi.stubEnv("ENEO_BACKEND_URL", "http://backend.test:8123");

    expect(proxiedBy(url)).toMatchObject({
      target: "http://backend.test:8123",
      changeOrigin: false
    });
  });

  it.each(["/", "/login", "/apikeys", "/versions", "/login/callbacks", "/spaces/api"])(
    "leaves the app path %s to the dev server",
    (url) => {
      vi.stubEnv("ENEO_BACKEND_URL", "http://backend.test:8123");

      expect(proxiedBy(url)).toBeUndefined();
    }
  );

  it("proxies WebSockets only under /api", () => {
    vi.stubEnv("ENEO_BACKEND_URL", "http://backend.test:8123");

    expect(proxiedBy("/api/v1/ws")?.ws).toBe(true);
    expect(proxiedBy("/version")?.ws).toBeUndefined();
  });

  it("refuses to start without a backend URL", () => {
    vi.stubEnv("ENEO_BACKEND_URL", "");

    expect(() => config(serve)).toThrow(/ENEO_BACKEND_URL/);
  });

  it("builds without a backend URL or a dev server", () => {
    vi.stubEnv("ENEO_BACKEND_URL", "");

    expect(config({ command: "build", mode: "production" }).server).toBeUndefined();
  });
});
