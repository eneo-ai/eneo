import { describe, expect, test, vi } from "vitest";
import { GET, HEAD } from "./+server";

const MODULE_KEY = "tal-till-text";
const REDIRECT_URI = "https://module.example/auth/callback";
const STATE = "opaque%26state%3Dvalue";

function moduleLoginUrl(): URL {
  const query = new URLSearchParams({
    module_key: MODULE_KEY,
    redirect_uri: REDIRECT_URI,
    state: STATE
  });
  return new URL(`https://eneo.example/module-login?${query.toString()}`);
}

function event({
  url = moduleLoginUrl(),
  idToken = "session-token",
  backendUrl = "https://backend.example",
  response = new Response(
    JSON.stringify({
      redirect_target: `${REDIRECT_URI}?ticket=one-time&state=${encodeURIComponent(STATE)}`,
      expires_in: 30
    }),
    { status: 201, headers: { "Content-Type": "application/json" } }
  )
}: {
  url?: URL;
  idToken?: string | null;
  backendUrl?: string | undefined;
  response?: Response;
} = {}) {
  const fetchFn = vi.fn().mockResolvedValue(response);
  const cookies = { delete: vi.fn() };
  return {
    input: {
      url,
      locals: {
        id_token: idToken,
        environment: { baseUrl: backendUrl }
      },
      fetch: fetchFn,
      cookies
    },
    fetchFn,
    cookies
  };
}

describe("public GET /module-login with an explicit session gate", () => {
  test("issues one ticket server-side and redirects only to the backend target", async () => {
    const fixture = event();

    const response = await GET(fixture.input as never);

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(
      `${REDIRECT_URI}?ticket=one-time&state=${encodeURIComponent(STATE)}`
    );
    expect(response.headers.get("cache-control")).toBe("private, no-store, max-age=0");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    expect(fixture.fetchFn).toHaveBeenCalledOnce();

    const [requestUrl, request] = fixture.fetchFn.mock.calls[0];
    expect(String(requestUrl)).toBe("https://backend.example/api/v1/module-auth/tickets/");
    expect(request.method).toBe("POST");
    expect(request.headers).toEqual({
      Authorization: "Bearer session-token",
      "Content-Type": "application/json"
    });
    expect(JSON.parse(request.body)).toEqual({
      module_key: MODULE_KEY,
      redirect_uri: REDIRECT_URI,
      state: STATE
    });
  });

  test("rejects missing or duplicated inputs without issuing a ticket", async () => {
    const missing = moduleLoginUrl();
    missing.searchParams.delete("state");
    const missingFixture = event({ url: missing });
    const missingResponse = await GET(missingFixture.input as never);

    expect(missingResponse.headers.get("location")).toBe(
      "/module-login/failed?reason=invalid_request"
    );
    expect(missingFixture.fetchFn).not.toHaveBeenCalled();

    const duplicated = moduleLoginUrl();
    duplicated.searchParams.append("module_key", "other-module");
    const duplicatedFixture = event({ url: duplicated });
    const duplicatedResponse = await GET(duplicatedFixture.input as never);

    expect(duplicatedResponse.headers.get("location")).toBe(
      "/module-login/failed?reason=invalid_request"
    );
    expect(duplicatedFixture.fetchFn).not.toHaveBeenCalled();

    const extra = moduleLoginUrl();
    extra.searchParams.set("unexpected", "value");
    const extraFixture = event({ url: extra });
    const extraResponse = await GET(extraFixture.input as never);

    expect(extraResponse.headers.get("location")).toBe(
      "/module-login/failed?reason=invalid_request"
    );
    expect(extraFixture.fetchFn).not.toHaveBeenCalled();
  });

  test("clears an invalid session and preserves the exact local handoff as next", async () => {
    const fixture = event({ response: new Response(null, { status: 401 }) });

    const response = await GET(fixture.input as never);

    const location = new URL(response.headers.get("location")!, "https://eneo.example");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe(
      fixture.input.url.pathname + fixture.input.url.search
    );
    expect(fixture.cookies.delete).toHaveBeenCalledWith("auth", { path: "/" });
    expect(fixture.cookies.delete).toHaveBeenCalledWith("acc", { path: "/" });
  });

  test.each([400, 403, 404])(
    "maps backend %s to a non-enumerating module error",
    async (status) => {
      const fixture = event({ response: new Response(null, { status }) });

      const response = await GET(fixture.input as never);

      expect(response.headers.get("location")).toBe(
        "/module-login/failed?reason=module_unavailable"
      );
    }
  );

  test("maps backend validation failure to an invalid request", async () => {
    const fixture = event({ response: new Response(null, { status: 422 }) });

    const response = await GET(fixture.input as never);

    expect(response.headers.get("location")).toBe("/module-login/failed?reason=invalid_request");
  });

  test("fails closed on backend outages and malformed success bodies", async () => {
    const unavailable = event({ response: new Response(null, { status: 503 }) });
    expect((await GET(unavailable.input as never)).headers.get("location")).toBe(
      "/module-login/failed?reason=service_unavailable"
    );

    const malformed = event({
      response: new Response(JSON.stringify({ redirect_target: "javascript:alert(1)" }), {
        status: 201,
        headers: { "Content-Type": "application/json" }
      })
    });
    expect((await GET(malformed.input as never)).headers.get("location")).toBe(
      "/module-login/failed?reason=service_unavailable"
    );
  });

  test("does not call the backend before authentication is present", async () => {
    const fixture = event({ idToken: null });

    const response = await GET(fixture.input as never);

    expect(new URL(response.headers.get("location")!, "https://eneo.example").pathname).toBe(
      "/login"
    );
    expect(response.headers.get("cache-control")).toBe("private, no-store, max-age=0");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    expect(fixture.fetchFn).not.toHaveBeenCalled();
  });
});

test("HEAD never creates a ticket", async () => {
  const fixture = event();

  const response = await HEAD(fixture.input as never);

  expect(response.status).toBe(405);
  expect(response.headers.get("allow")).toBe("GET");
  expect(fixture.fetchFn).not.toHaveBeenCalled();
});
