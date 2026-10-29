// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.hoisted(() => vi.fn());
const clear = vi.hoisted(() => vi.fn());
const cancelQueries = vi.hoisted(() => vi.fn(async () => {}));
vi.mock("@/lib/navigate-to", () => ({ navigateTo: navigate }));
vi.mock("@/lib/api/query", () => ({ getQueryClient: () => ({ clear, cancelQueries }) }));

const GENERATION = "Eneo-Session-Generation";
const probe = (generation = "document-session") =>
  new Response(null, { status: 204, headers: { [GENERATION]: generation } });
const refusal = (code?: number, status = 401, headers?: Record<string, string>) =>
  new Response(JSON.stringify({ message: "Refused", eneo_error_code: code }), {
    status,
    headers: { "content-type": "application/json", ...headers }
  });

let owner: typeof import("./refusal");
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/spaces/x?a=1");
  fetcher = vi.fn<typeof fetch>().mockResolvedValue(probe());
  vi.stubGlobal("fetch", fetcher);
  owner = await import("./refusal");
});
afterEach(() => vi.unstubAllGlobals());

async function bound() {
  await owner.initializeBrowserSession();
  fetcher.mockClear();
}

describe("immutable document session", () => {
  it("leaves a refused personal Skill save with its form instead of expiring the session", async () => {
    await bound();
    const response = refusal(9080, 400, { [GENERATION]: "document-session" });
    await owner.handleRefusal(response, "/api/v1/spaces/personal/skills/");
    expect(owner.getSessionSnapshot().status).toBe("bound");
    expect(navigate).not.toHaveBeenCalled();
    expect(clear).not.toHaveBeenCalled();
  });

  it("keeps a suspended bootstrap identity-free so its public recovery can render", async () => {
    window.history.replaceState({}, "", "/deactivated");
    fetcher.mockResolvedValueOnce(refusal(9025, 403, { [GENERATION]: "suspended" }));
    await owner.initializeBrowserSession();
    expect(owner.getSessionSnapshot()).toEqual({ status: "deactivated", generation: "suspended" });
    await expect(owner.requireBrowserSession()).rejects.toMatchObject({ code: 9025 });
    fetcher.mockResolvedValueOnce(probe("reactivated-session"));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9025 });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("binds an unusable bootstrap cookie only for logout and refuses a replacement on resume", async () => {
    window.history.replaceState({}, "", "/logout");
    fetcher.mockResolvedValueOnce(refusal(9005, 401, { [GENERATION]: "expired" }));
    await owner.initializeBrowserSession();
    expect(owner.getSessionSnapshot()).toEqual({
      status: "bound",
      generation: null,
      logoutGeneration: "expired"
    });
    await expect(owner.requireBrowserSession()).rejects.toMatchObject({ status: 401 });
    fetcher.mockResolvedValueOnce(probe("new-session"));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9090 });
    expect(fetcher.mock.calls[1]![1]!.headers).toEqual(new Headers({ [GENERATION]: "expired" }));
    expect(owner.getSessionSnapshot().status).toBe("stale");
  });

  it("does not silently adopt a rejected cookie in a document that booted without one", async () => {
    window.history.replaceState({}, "", "/login");
    fetcher.mockResolvedValueOnce(refusal());
    await owner.initializeBrowserSession();
    fetcher.mockResolvedValueOnce(refusal(9005, 401, { [GENERATION]: "later-cookie" }));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9090 });
  });

  it("keeps the same unusable cookie bound only to logout after a resume check", async () => {
    window.history.replaceState({}, "", "/logout");
    fetcher.mockResolvedValue(refusal(9005, 401, { [GENERATION]: "expired" }));
    await owner.initializeBrowserSession();
    await owner.checkBrowserSession();
    expect(owner.getSessionSnapshot()).toEqual({
      status: "bound",
      generation: null,
      logoutGeneration: "expired"
    });
    await expect(owner.requireBrowserSession()).rejects.toMatchObject({ status: 401 });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("bootstraps once, then sends its generation on reads and writes", async () => {
    await Promise.all([owner.initializeBrowserSession(), owner.initializeBrowserSession()]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    for (const method of ["GET", "POST"]) {
      const request = await owner.prepareBrowserRequest(
        new Request("https://eneo.test/api", { method })
      );
      expect(request.headers.get(GENERATION)).toBe("document-session");
    }
  });

  it("refuses a replacement response before its body can reach a consumer", async () => {
    await bound();
    const request = await owner.prepareBrowserRequest(new Request("https://eneo.test/api"));
    await expect(
      owner.handleRefusal(probe("another-session"), "/api/v1/users/me/")
    ).rejects.toMatchObject({ code: 9090 });
    expect(request.signal.aborted).toBe(true);
    expect(clear).toHaveBeenCalledTimes(1);
    expect(cancelQueries).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Fspaces%2Fx%3Fa%3D1");
    await expect(
      owner.prepareBrowserRequest(new Request("https://eneo.test/api", { method: "POST" }))
    ).rejects.toMatchObject({ code: 9090 });
    expect(fetcher).not.toHaveBeenCalled();
    expect(owner.getSessionSnapshot().status).toBe("stale");
  });

  it("navigates once for concurrent refusals and remains blocked when assign returns", async () => {
    await bound();
    await Promise.allSettled([
      owner.handleRefusal(refusal(9090), "/api"),
      owner.handleRefusal(refusal(9090), "/api")
    ]);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(owner.getSessionSnapshot().status).toBe("stale");
    await expect(owner.handleRefusal(probe(), "/api")).rejects.toMatchObject({ code: 9090 });
  });

  it("processes mismatch before audit and public-page exemptions", async () => {
    await bound();
    window.history.replaceState({}, "", "/login");
    await expect(
      owner.handleRefusal(
        refusal(9090, 401, { "X-Error-Code": "AUDIT_SESSION_REQUIRED" }),
        "/api/v1/audit/logs/"
      )
    ).rejects.toMatchObject({ code: 9090 });
    expect(navigate).not.toHaveBeenCalled();
    expect(owner.getSessionSnapshot().status).toBe("stale");
  });

  it("does not mistake network or server failure for identity change", async () => {
    await bound();
    fetcher.mockRejectedValueOnce(new TypeError("Offline"));
    await expect(owner.checkBrowserSession()).rejects.toThrow("Offline");
    expect(owner.getSessionSnapshot().status).toBe("bound");
    await expect(owner.prepareBrowserRequest(new Request("https://eneo.test/api"))).rejects.toThrow(
      "Offline"
    );
    fetcher.mockResolvedValueOnce(refusal(undefined, 503));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ status: 503 });
    expect(navigate).not.toHaveBeenCalled();
    fetcher.mockResolvedValueOnce(probe());
    await owner.checkBrowserSession();
    await expect(
      owner.prepareBrowserRequest(new Request("https://eneo.test/api"))
    ).resolves.toBeInstanceOf(Request);
  });

  it("gates work behind the one pending resume probe", async () => {
    await bound();
    let finish!: (response: Response) => void;
    fetcher.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const checking = owner.checkBrowserSession();
    const prepared = vi.fn();
    const work = owner.prepareBrowserRequest(new Request("https://eneo.test/api")).then(prepared);
    await Promise.resolve();
    expect(prepared).not.toHaveBeenCalled();
    finish(probe());
    await Promise.all([checking, work]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(prepared).toHaveBeenCalledTimes(1);
  });

  it("checks visibility before an earlier feature listener can prepare its autosave", async () => {
    await bound();
    let finish!: (response: Response) => void;
    fetcher.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const prepared = vi.fn();
    let work: Promise<unknown> | undefined;
    const autosave = () => {
      work = owner
        .prepareBrowserRequest(new Request("https://eneo.test/api", { method: "POST" }))
        .then(prepared);
    };
    document.addEventListener("visibilitychange", autosave);
    const stop = owner.listenForSessionResume();
    try {
      document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
      await Promise.resolve();
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(prepared).not.toHaveBeenCalled();
      finish(probe());
      await work;
      expect(prepared).toHaveBeenCalledTimes(1);
    } finally {
      stop();
      document.removeEventListener("visibilitychange", autosave);
    }
  });

  it("checks restored pages but does not probe on ordinary pageshow or after cleanup", async () => {
    await bound();
    const stop = owner.listenForSessionResume();
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: false }));
    expect(fetcher).not.toHaveBeenCalled();
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    await owner.checkBrowserSession();
    expect(fetcher).toHaveBeenCalledTimes(1);
    stop();
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("keeps an unchanged anonymous document usable but never adopts a new cookie", async () => {
    window.history.replaceState({}, "", "/login");
    fetcher.mockResolvedValue(refusal(9005));
    await owner.initializeBrowserSession();
    await owner.checkBrowserSession();
    expect(owner.getSessionSnapshot()).toMatchObject({ status: "bound", generation: null });
    expect(navigate).not.toHaveBeenCalled();
    fetcher.mockResolvedValue(probe("new-account"));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9090 });
    expect(owner.getSessionSnapshot().status).toBe("stale");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("treats logout or expiry of an authenticated session as stale", async () => {
    await bound();
    fetcher.mockResolvedValue(refusal(9005));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9090 });
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("sends an anonymous protected-page visit to login without trying the cookie again", async () => {
    fetcher.mockResolvedValue(refusal(9005));
    await owner.initializeBrowserSession();
    fetcher.mockClear();
    await expect(
      owner.prepareBrowserRequest(new Request("https://eneo.test/api"))
    ).rejects.toMatchObject({ code: 9090 });
    expect(fetcher).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("rejects a successful response without an admitted session header", async () => {
    await bound();
    await expect(owner.handleRefusal(new Response("private data"), "/api")).rejects.toMatchObject({
      status: 502
    });
    expect(navigate).not.toHaveBeenCalled();
  });
});

describe("refusal routing", () => {
  it.each<[number | undefined, number, string]>([
    [undefined, 401, "/login?next=%2Fspaces%2Fx%3Fa%3D1"],
    [9025, 403, "/deactivated"],
    [9070, 403, "/password-change?next=%2Fspaces%2Fx%3Fa%3D1"]
  ])("routes %s/%s through a document load", async (code, status, destination) => {
    await bound();
    await expect(owner.handleRefusal(refusal(code, status), "/api")).rejects.toMatchObject({
      status
    });
    expect(navigate).toHaveBeenCalledExactlyOnceWith(destination);
  });

  it("exempts explicit audit refusals, never arbitrary 401s at audit URLs", async () => {
    await bound();
    await owner.handleRefusal(
      refusal(undefined, 401, { "X-Error-Code": "AUDIT_SESSION_REQUIRED" }),
      "/api/v1/audit/logs/"
    );
    expect(navigate).not.toHaveBeenCalled();
    await expect(owner.handleRefusal(refusal(), "/api/v1/audit/logs/")).rejects.toMatchObject({
      status: 401
    });
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("leaves ordinary errors and public-page refusals to their caller", async () => {
    await bound();
    await owner.handleRefusal(refusal(9001, 403), "/api");
    await owner.handleRefusal(refusal(undefined, 500), "/api");
    window.history.replaceState({}, "", "/module-login");
    await owner.handleRefusal(refusal(), "/api");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("preserves diagnostic fields and the caller's response body when it ends the session", async () => {
    await bound();
    const response = Response.json(
      {
        message: "Session expired",
        eneo_error_code: 9005,
        error_id: "error-reference"
      },
      { status: 401, headers: { "x-trace-id": "trace-reference" } }
    );
    await expect(owner.handleRefusal(response, "/api")).rejects.toMatchObject({
      status: 401,
      code: 9005,
      traceId: "trace-reference",
      errorId: "error-reference"
    });
    expect(response.bodyUsed).toBe(false);
  });
});
