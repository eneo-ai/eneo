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

describe("frontend release identity", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("leaves identity unset when a local build supplies no release metadata", () => {
    vi.stubEnv("APP_VERSION", undefined);
    vi.stubEnv("APP_REVISION", undefined);

    expect(config({ command: "build", mode: "production" }).define).toEqual({
      "import.meta.env.APP_VERSION": JSON.stringify(""),
      "import.meta.env.APP_REVISION": JSON.stringify("")
    });
  });

  it("embeds only the two explicit public release values", () => {
    vi.stubEnv("APP_VERSION", "feature/example-123456789abc");
    vi.stubEnv("APP_REVISION", "123456789abcdef123456789abcdef123456789ab");
    vi.stubEnv("PRIVATE_TEST_VALUE", "must-not-be-bundled");

    const values = config({ command: "build", mode: "production" }).define;
    expect(values).toEqual({
      "import.meta.env.APP_VERSION": JSON.stringify("feature/example-123456789abc"),
      "import.meta.env.APP_REVISION": JSON.stringify("123456789abcdef123456789abcdef123456789ab")
    });
  });
});
