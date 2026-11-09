import { describe, expect, test, vi } from "vitest";
import { actions, load } from "./+page.server";

const SECRET = "s3cret-value-never-echoed";

const view = {
  configured: true,
  provider: "Entra ID",
  discovery_endpoint: "https://idp.example/.well-known/openid-configuration",
  issuer: "https://idp.example",
  client_id: "client-a",
  client_secret_set: true,
  client_secret_updated_at: "2026-11-01T10:00:00Z",
  encryption_status: "encrypted",
  allowed_domains: ["example.com"],
  redirect_uris: ["https://eneo.example/login/callback"],
  scopes: ["openid", "email", "profile"],
  token_endpoint_auth_method: "client_secret_post",
  revision: "rev-1"
};

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}

function backend(answer: () => Response | Promise<Response>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void input;
    void init;
    return answer();
  });
}

function event(fetch: ReturnType<typeof backend>, form?: FormData) {
  return {
    fetch,
    depends: vi.fn(),
    locals: { id_token: "eneo-session-token", environment: { baseUrl: "https://api.example" } },
    request: new Request("https://eneo.example/admin/federation?/save", {
      method: "POST",
      body: form ?? new FormData()
    })
  };
}

function saveForm(entries: [string, string][]) {
  const form = new FormData();
  for (const [name, value] of entries) form.append(name, value);
  return form;
}

async function loaded(fetch: ReturnType<typeof backend>) {
  const result = (await load(event(fetch) as never)) as { federation: Promise<unknown> };
  return result.federation;
}

describe("loading the sign-in settings", () => {
  test("reads the caller's organisation with their session", async () => {
    const fetch = backend(() => json(200, view));

    expect(await loaded(fetch)).toEqual({ kind: "ready", view });
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toBe("https://api.example/api/v1/admin/federation");
    expect(init?.method).toBe("GET");
    expect(new Headers(init?.headers).get("authorization")).toBe("Bearer eneo-session-token");
  });

  test("tells a missing registration apart from an installation without federation", async () => {
    expect(await loaded(backend(() => json(200, { configured: false })))).toEqual({
      kind: "unconfigured"
    });
    expect(
      await loaded(
        backend(() =>
          json(404, { detail: { code: "federation_disabled", message: "Federation is off." } })
        )
      )
    ).toEqual({ kind: "disabled" });
  });

  test("any other failure is an error the page can retry, never a rejection", async () => {
    expect(await loaded(backend(() => json(403, { detail: "Forbidden" })))).toEqual({
      kind: "error"
    });
    expect(
      await loaded(
        backend(() => {
          throw new TypeError("fetch failed");
        })
      )
    ).toEqual({ kind: "error" });
  });
});

describe("saving the sign-in settings", () => {
  async function save(fetch: ReturnType<typeof backend>, form: FormData) {
    return actions.save!(event(fetch, form) as never);
  }

  test("sends only the settings an admin owns and answers with the fresh view", async () => {
    const fetch = backend(() => json(200, { ...view, revision: "rev-2" }));

    const result = await save(
      fetch,
      saveForm([
        ["revision", "rev-1"],
        ["client_secret", SECRET],
        ["allowed_domains", "example.com\nexample.org"],
        ["discovery_endpoint", "https://evil.example/.well-known/openid-configuration"]
      ])
    );

    expect(result).toEqual({ view: { ...view, revision: "rev-2" } });
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toBe("https://api.example/api/v1/admin/federation");
    expect(init?.method).toBe("PATCH");
    expect(new Headers(init?.headers).get("authorization")).toBe("Bearer eneo-session-token");
    expect(JSON.parse(String(init?.body))).toEqual({
      revision: "rev-1",
      client_secret: SECRET,
      allowed_domains: ["example.com", "example.org"]
    });
  });

  test.each([
    [409, { detail: { code: "federation_config_revision_conflict" } }, { code: "conflict" }],
    [404, { detail: { code: "federation_not_configured" } }, { code: "not_configured" }],
    [404, { detail: { code: "federation_disabled" } }, { code: "disabled" }],
    [
      503,
      { detail: { code: "federation_encryption_unavailable" } },
      { code: "encryption_unavailable" }
    ],
    [
      400,
      { detail: { code: "federation_secret_looks_masked" } },
      { code: "fields", fields: { client_secret: "secret_masked" } }
    ],
    [
      422,
      {
        detail: [
          { loc: ["body", "client_secret"], type: "value_error", msg: "Invalid value" },
          { loc: ["body", "allowed_domains", 0], type: "value_error", msg: "Invalid value" }
        ]
      },
      { code: "fields", fields: { client_secret: "refused", allowed_domains: "refused" } }
    ],
    [422, { detail: [{ loc: ["body"], type: "missing" }] }, { code: "request_failed" }],
    [403, { detail: { code: "session_auth_required" } }, { code: "request_failed" }],
    [500, { message: "boom" }, { code: "request_failed" }]
  ])(
    "a %i refusal comes back as a code and never with the secret",
    async (status, body, failure) => {
      const result = await save(
        backend(() => json(status, body)),
        saveForm([
          ["revision", "rev-1"],
          ["client_secret", SECRET]
        ])
      );

      expect(result).toMatchObject({ status, data: { failure } });
      expect(JSON.stringify(result)).not.toContain(SECRET);
    }
  );

  test("an unreachable backend is a failed save, not a thrown error", async () => {
    const result = await save(
      backend(() => {
        throw new TypeError(`fetch failed for ${SECRET}`);
      }),
      saveForm([
        ["revision", "rev-1"],
        ["client_secret", SECRET]
      ])
    );

    expect(result).toMatchObject({ status: 500, data: { failure: { code: "request_failed" } } });
    expect(JSON.stringify(result)).not.toContain(SECRET);
  });

  test("a form without a revision is refused before the backend is called", async () => {
    const fetch = backend(() => json(200, view));

    const result = await save(fetch, saveForm([["provider", "Okta"]]));

    expect(result).toMatchObject({ status: 400, data: { failure: { code: "request_failed" } } });
    expect(fetch).not.toHaveBeenCalled();
  });
});
