import { afterEach, describe, expect, test, vi } from "vitest";
import { EneoError } from "@eneo/eneo-js";

const environment = vi.hoisted(() => ({ browser: false }));
vi.mock("$app/environment", () => environment);

import { load } from "./+layout";

afterEach(() => {
  environment.browser = false;
  vi.unstubAllGlobals();
});

function event(fetch: typeof globalThis.fetch) {
  // Only the load's used request fields are needed; SvelteKit supplies the
  // remaining framework services in production.
  const request: Pick<Parameters<typeof load>[0], "depends" | "url" | "fetch" | "data"> = {
    depends: vi.fn(),
    url: new URL("https://eneo.example/dashboard"),
    fetch,
    data: {
      tokens: { id_token: "password-token", access_token: null },
      environment: {
        baseUrl: "https://backend.example",
        authUrl: undefined,
        integrationRequestFormUrl: undefined,
        helpCenterUrl: "https://eneo.example/help",
        newAppUrl: undefined,
        frontendVersion: "test",
        gitInfo: undefined
      },
      featureFlags: {
        newAuth: false,
        showHelpCenter: false,
        showNewAppBanner: false,
        federationStatus: {
          has_single_tenant_federation: false,
          has_multi_tenant_federation: false,
          has_global_oidc_config: false,
          tenant_count: 0
        }
      }
    }
  };
  return request as Parameters<typeof load>[0];
}

function refusal(code = 9070) {
  return Response.json({ message: "Request refused", eneo_error_code: code }, { status: 403 });
}

describe("password-change recovery through the app's API client", () => {
  test("redirects during the initial server load", async () => {
    await expect(load(event(async () => refusal()))).rejects.toMatchObject({
      status: 302,
      location: "/password-change?next=%2Fdashboard"
    });
  });

  test("redirects a later refusal without reloading the layout, using the current page", async () => {
    environment.browser = true;
    const assign = vi.fn();
    const location = { href: "https://eneo.example/dashboard", assign };
    vi.stubGlobal("window", { location });
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockImplementation(async () => Response.json({}));
    const app = await load(event(fetch));
    expect(assign).not.toHaveBeenCalled();

    // A policy change/expiry happens after load and after client-side navigation.
    location.href = "https://eneo.example/spaces/current?tab=files";
    fetch.mockImplementation(async () => refusal());
    await expect(app.eneo.users.tenant()).rejects.toBeInstanceOf(EneoError);
    expect(assign).toHaveBeenCalledWith("/password-change?next=%2Fspaces%2Fcurrent%3Ftab%3Dfiles");
  });

  test("keeps ordinary permission errors on the current page", async () => {
    environment.browser = true;
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { href: "https://eneo.example/dashboard", assign } });
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockImplementation(async () => Response.json({}));
    const app = await load(event(fetch));
    fetch.mockImplementation(async () => refusal(9001));

    await expect(app.eneo.users.tenant()).rejects.toMatchObject({ status: 403, code: 9001 });
    expect(assign).not.toHaveBeenCalled();
  });
});
