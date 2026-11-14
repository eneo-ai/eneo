import { beforeEach, describe, expect, test, vi } from "vitest";

const state = vi.hoisted(() => ({
  env: {} as Record<string, string>,
  cookies: new Map<string, string>(),
  fetch: vi.fn(),
  setFrontendAuthCookie: vi.fn()
}));

vi.mock("$env/dynamic/private", () => ({ env: state.env }));
vi.mock("$app/server", () => ({
  getRequestEvent: () => ({
    url: new URL("https://eneo.example/login/callback"),
    cookies: {
      get: (name: string) => state.cookies.get(name),
      delete: (name: string) => state.cookies.delete(name)
    },
    fetch: state.fetch
  })
}));
vi.mock("./auth.server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./auth.server")>()),
  setFrontendAuthCookie: state.setFrontendAuthCookie
}));

import type { Cookies } from "@sveltejs/kit";
import { LoginError } from "./LoginError";
import { clearZitadelCookie, getZitadelLink, loginWithZitadel } from "./zitadel.server";

const VERIFIER_COOKIE = "zitadel-verifier";
const AUD_SCOPE = "urn:zitadel:iam:org:project:id:zitadel:aud";

function eventCookies() {
  return {
    set: vi.fn((name: string, value: string) => state.cookies.set(name, value)),
    delete: vi.fn((name: string) => state.cookies.delete(name))
  } as unknown as Cookies & { set: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn> };
}

beforeEach(() => {
  vi.clearAllMocks();
  state.cookies.clear();
  Object.assign(state.env, {
    ZITADEL_PROJECT_CLIENT_ID: "zitadel-client",
    ZITADEL_INSTANCE_URL: "https://zitadel.example",
    PUBLIC_ORIGIN: "https://eneo.example"
  });
});

describe("the Zitadel authorization link", () => {
  test("asks for the project audience with PKCE S256 and stores the verifier", async () => {
    const cookies = eventCookies();
    const link = await getZitadelLink({ url: new URL("https://eneo.example/login"), cookies });

    const url = new URL(link!);
    expect(`${url.origin}${url.pathname}`).toBe("https://zitadel.example/oauth/v2/authorize");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      scope: `openid email ${AUD_SCOPE}`,
      client_id: "zitadel-client",
      response_type: "code",
      redirect_uri: "https://eneo.example/login/callback",
      state: JSON.stringify({ loginMethod: "zitadel", next: null }),
      code_challenge: expect.stringMatching(/^[A-Za-z0-9_-]{43}$/),
      code_challenge_method: "S256"
    });
    expect(cookies.set).toHaveBeenCalledWith(
      VERIFIER_COOKIE,
      expect.any(String),
      expect.objectContaining({ path: "/", httpOnly: true, sameSite: "lax" })
    );
  });

  test("an invitation names the organisation and asks to create the user", async () => {
    const link = await getZitadelLink(
      { url: new URL("https://eneo.example/invite/org-1"), cookies: eventCookies() },
      { registerUser: true, orgId: "org-1" }
    );

    const params = new URL(link!).searchParams;
    expect(params.get("scope")).toBe(`openid email ${AUD_SCOPE} urn:zitadel:iam:org:id:org-1`);
    expect(params.get("prompt")).toBe("create");
  });
});

describe("the Zitadel code exchange", () => {
  test("redeems the code at Zitadel and keeps both tokens", async () => {
    state.cookies.set(VERIFIER_COOKIE, "stored-verifier");
    const tokens = { id_token: "zitadel-id-token", access_token: "zitadel-access-token" };
    state.fetch.mockResolvedValue(new Response(JSON.stringify(tokens), { status: 200 }));

    expect(await loginWithZitadel("the-code")).toBe(true);

    expect(state.fetch).toHaveBeenCalledOnce();
    const [url, request] = state.fetch.mock.calls[0];
    const tokenUrl = new URL(url);
    expect(`${tokenUrl.origin}${tokenUrl.pathname}`).toBe("https://zitadel.example/oauth/v2/token");
    expect(Object.fromEntries(tokenUrl.searchParams)).toEqual({
      client_id: "zitadel-client",
      code: "the-code",
      code_verifier: "stored-verifier",
      grant_type: "authorization_code",
      redirect_uri: "https://eneo.example/login/callback"
    });
    expect(request.method).toBe("POST");
    expect(state.setFrontendAuthCookie).toHaveBeenCalledWith(tokens);
    expect(state.cookies.has(VERIFIER_COOKIE)).toBe(false);
  });

  test.each([
    ["the token endpoint refuses", "NO_TOKEN", true, 400],
    ["the verifier cookie is gone", "NO_VERIFIER", false, 200]
  ])("%s: %s", async (_, code, withVerifier, status) => {
    if (withVerifier) state.cookies.set(VERIFIER_COOKIE, "stored-verifier");
    state.fetch.mockResolvedValue(new Response("{}", { status }));

    const error = await loginWithZitadel("the-code").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(LoginError);
    expect(error).toMatchObject({ provider: "zitadel", code });
    expect(state.setFrontendAuthCookie).not.toHaveBeenCalled();
  });

  test("without its configuration the exchange is refused", async () => {
    delete state.env.ZITADEL_INSTANCE_URL;

    await expect(loginWithZitadel("the-code")).rejects.toMatchObject({ code: "NO_CONFIG" });
    expect(state.fetch).not.toHaveBeenCalled();
  });

  test("clearing removes the verifier cookie", () => {
    const cookies = eventCookies();

    clearZitadelCookie(cookies);

    expect(cookies.delete).toHaveBeenCalledWith(VERIFIER_COOKIE, { path: "/" });
  });
});
