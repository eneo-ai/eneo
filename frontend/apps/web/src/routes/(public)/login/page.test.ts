import { deserialize } from "$app/forms";
import { readInstanceScript, runInstanceScript } from "$lib/test/instanceScript";
import { describe, expect, test, vi } from "vitest";

// Run the page's actual instance script; see $lib/test/instanceScript for why.
const script = readInstanceScript(new URL("./+page.svelte", import.meta.url));

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
  let mounted: (() => Promise<void>) | undefined;
  const identityDerived = Object.assign((value: unknown) => value, {
    by: (value: () => unknown) => value()
  });
  const { flow } = runInstanceScript<{
    flow: {
      begin: (slug?: string) => Promise<boolean>;
      retry: () => Promise<void>;
      redirect: () => void;
      state: () => { awaiting: boolean; initializing: boolean; error: string | null };
    };
  }>(script, {
    filename: "login-page.js",
    epilogue: [
      "exports.flow = {",
      "  begin: beginOidcLogin,",
      "  retry: retryTenantLogin,",
      "  redirect: redirectToExternalLogin,",
      "  state: () => ({",
      "    awaiting: isAwaitingLoginResponse,",
      "    initializing: isInitializing,",
      "    error: federationError",
      "  })",
      "};"
    ].join("\n"),
    modules: {
      "$app/state": { page: route },
      "$app/forms": { deserialize },
      "$app/navigation": { goto: async () => undefined },
      "$app/environment": { browser: true },
      svelte: {
        onMount: (callback: () => Promise<void>) => {
          mounted = callback;
        }
      },
      "svelte/motion": { prefersReducedMotion: { current: true } },
      "svelte/reactivity": { SvelteURLSearchParams: URLSearchParams },
      "$lib/paraglide/messages": {
        m: new Proxy({}, { get: (_target, key) => () => String(key) })
      }
    },
    globals: {
      $props: () => ({
        data: {
          hasSingleTenantOidc: mode === "single",
          featureFlags: { federationStatus: { has_multi_tenant_federation: mode === "multi" } }
        }
      }),
      $state: (value: unknown) => value,
      $derived: identityDerived,
      // Effects are run explicitly through `flow.redirect`.
      $effect: () => undefined,
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
    }
  });
  if (mounted === undefined) throw new Error("Login script did not register its mount behavior");
  return { flow, window, fetch, mounted };
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
    browser.flow.redirect();
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
    "oidc_attempt_rejected",
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
