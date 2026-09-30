import { deserialize } from "$app/forms";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { parse } from "svelte/compiler";
import { ModuleKind, ScriptTarget, transpileModule } from "typescript";
import { describe, expect, test, vi } from "vitest";

// Execute the actual client instance script, replacing only framework/browser
// boundaries. Server-only Svelte compilation would remove its lifecycle code.
const source = readFileSync(new URL("./+page.svelte", import.meta.url), "utf8");
const instance = parse(source, { modern: true }).instance;
if (instance === null) throw new Error("Login page has no instance script");
const content = instance.content;
if (
  !("start" in content) ||
  !("end" in content) ||
  typeof content.start !== "number" ||
  typeof content.end !== "number"
) {
  throw new Error("Login script has no source offsets");
}
const script = transpileModule(source.slice(content.start, content.end), {
  compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 }
}).outputText;

function loginBrowser(
  response: Response,
  options: { message?: string; mode?: "single" | "multi"; rememberedTenant?: string } = {}
) {
  const { message, mode = "single", rememberedTenant } = options;
  const route = {
    url: new URL("https://eneo.example/login?next=%2Fmodule-login%3Fstate%3Da%252526b")
  };
  if (message !== undefined) route.url.searchParams.set("message", message);
  const window = {
    location: { href: route.url.href, pathname: route.url.pathname, search: route.url.search }
  };
  const fetch = vi.fn().mockResolvedValue(response);
  const storage = new Map<string, string>();
  if (rememberedTenant !== undefined) storage.set("eneo-last-tenant-slug", rememberedTenant);
  const effects: Array<() => void> = [];
  let mounted: (() => Promise<void>) | undefined;
  const exported: {
    flow?: {
      begin: (slug?: string) => Promise<boolean>;
      retry: () => Promise<void>;
      state: () => { awaiting: boolean; initializing: boolean; error: string | null };
    };
  } = {};
  const identityDerived = Object.assign((value: unknown) => value, {
    by: (value: () => unknown) => value()
  });
  runInNewContext(
    `${script}\nexports.flow = { begin: beginOidcLogin, retry: retryTenantLogin, state: () => ({ awaiting: isAwaitingLoginResponse, initializing: isInitializing, error: federationError }) };`,
    {
      exports: exported,
      require: (name: string) => {
        if (name === "$app/state") return { page: route };
        if (name === "$app/forms") return { deserialize };
        if (name === "$app/navigation") return { goto: async () => undefined };
        if (name === "$app/environment") return { browser: true };
        if (name === "svelte") {
          return {
            onMount: (callback: () => Promise<void>) => {
              mounted = callback;
            }
          };
        }
        if (name === "svelte/motion") return { prefersReducedMotion: { current: true } };
        if (name === "svelte/reactivity") return { SvelteURLSearchParams: URLSearchParams };
        if (name === "$lib/paraglide/messages") {
          return {
            m: new Proxy({}, { get: (_target, key) => () => String(key) })
          };
        }
        throw new Error(`Unexpected login script import: ${name}`);
      },
      $props: () => ({
        data: {
          hasSingleTenantOidc: mode === "single",
          featureFlags: { federationStatus: { has_multi_tenant_federation: mode === "multi" } }
        }
      }),
      $state: (value: unknown) => value,
      $derived: identityDerived,
      $effect: (effect: () => void) => effects.push(effect),
      window,
      sessionStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
        removeItem: (key: string) => storage.delete(key)
      },
      fetch,
      FormData,
      URLSearchParams,
      console
    },
    { timeout: 1000, filename: "login-page.js" }
  );
  if (exported.flow === undefined) throw new Error("Login script did not expose its flow");
  if (mounted === undefined) throw new Error("Login script did not register its mount behavior");
  return { flow: exported.flow, window, fetch, effects, mounted };
}

describe("login initiation client transport", () => {
  test.each([undefined, "sundsvall"])(
    "single/multi-tenant login %s sends a JSON action request and navigates only after its redirect",
    async (slug) => {
      const browser = loginBrowser(
        new Response(
          JSON.stringify({
            type: "redirect",
            status: 303,
            location: "https://idp.example/authorize"
          })
        ),
        { mode: slug === undefined ? "single" : "multi" }
      );
      await expect(browser.flow.begin(slug)).resolves.toBe(true);

      expect(browser.fetch).toHaveBeenCalledOnce();
      const [url, options] = browser.fetch.mock.calls[0];
      expect(url).toBe("?/oidc");
      expect(options.method).toBe("POST");
      expect(options.headers).toEqual({ Accept: "application/json", "x-sveltekit-action": "true" });
      expect(options.body.get("tenant")).toBe(slug ?? null);
      expect(options.body.get("next")).toBe("/module-login?state=a%2526b");
      expect(options.body.has("state")).toBe(false);
      expect(browser.window.location.href).toBe("https://idp.example/authorize");
    }
  );

  test("failed single-tenant initiation ends the loader, exposes a failure, and waits for explicit retry", async () => {
    const browser = loginBrowser(new Response(JSON.stringify({ type: "failure", status: 503 })));
    await expect(browser.flow.begin()).resolves.toBe(false);
    expect(browser.flow.state()).toEqual({
      awaiting: false,
      initializing: false,
      error: "failed_to_start_authentication"
    });
    expect(browser.window.location.href).toContain("https://eneo.example/login");

    // The actual automatic-redirect effect must not repeatedly retry this failure.
    browser.effects[2]();
    expect(browser.fetch).toHaveBeenCalledOnce();
    browser.fetch.mockResolvedValue(
      new Response(
        JSON.stringify({ type: "redirect", status: 303, location: "https://idp.example/authorize" })
      )
    );
    await expect(browser.flow.begin()).resolves.toBe(true);
    expect(browser.fetch).toHaveBeenCalledTimes(2);
  });

  test.each([
    "oidc_invalid_request",
    "no_code_received",
    "no_state_received",
    "oidc_oauth_error",
    "oidc_access_denied",
    "oidc_unauthorized_client",
    "oidc_server_error",
    "oidc_temporarily_unavailable"
  ])("the tenant mount waits for explicit retry on the %s error view", async (message) => {
    const browser = loginBrowser(new Response(), { message, mode: "multi" });
    await browser.mounted();
    expect(browser.fetch).not.toHaveBeenCalled();
    expect(browser.flow.state().initializing).toBe(false);
    expect(browser.window.location.href).toContain(`message=${message}`);
  });

  test("single-tenant retry ignores an organisation remembered in an earlier multi-tenant session", async () => {
    const browser = loginBrowser(new Response(JSON.stringify({ type: "failure", status: 503 })), {
      rememberedTenant: "old-organisation"
    });
    await browser.mounted();
    await expect(browser.flow.begin()).resolves.toBe(false);
    expect(browser.flow.state().initializing).toBe(false);
    browser.fetch.mockResolvedValue(
      new Response(
        JSON.stringify({ type: "redirect", status: 303, location: "https://idp.example/authorize" })
      )
    );
    await browser.flow.retry();
    expect(browser.fetch).toHaveBeenCalledTimes(2);
    for (const [, request] of browser.fetch.mock.calls) {
      expect(request.body.get("tenant")).toBeNull();
    }
    expect(browser.window.location.href).toBe("https://idp.example/authorize");
  });
});
