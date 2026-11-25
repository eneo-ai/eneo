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
    expect(owner.getSessionSnapshot()).toEqual({
      status: "deactivated",
      generation: "suspended",
      restriction: 9025
    });
    await expect(owner.requireBrowserSession()).rejects.toMatchObject({ code: 9025 });
    fetcher.mockResolvedValueOnce(probe("reactivated-session"));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9025 });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("keeps an inactive account's bootstrap identity-free and sends it to its recovery", async () => {
    window.history.replaceState({}, "", "/login");
    fetcher.mockResolvedValueOnce(refusal(9019, 403, { [GENERATION]: "inactive" }));
    await owner.initializeBrowserSession();
    expect(owner.getSessionSnapshot()).toEqual({
      status: "deactivated",
      generation: "inactive",
      restriction: 9019
    });
    await expect(owner.requireBrowserSession()).rejects.toMatchObject({ status: 403, code: 9019 });
    // A later cookie (another tab signed in) is never adopted by this document.
    fetcher.mockResolvedValueOnce(probe("replacement-session"));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9019 });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/deactivated", { replace: true });
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
    // Another sign-in holds the cookie: never resume this page's deep link as it.
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login", { replace: true });
    await expect(
      owner.prepareBrowserRequest(new Request("https://eneo.test/api", { method: "POST" }))
    ).rejects.toMatchObject({ code: 9090 });
    expect(fetcher).not.toHaveBeenCalled();
    expect(owner.getSessionSnapshot().status).toBe("stale");
  });

  it("sends a page whose session another sign-in replaced to sign-in, not to its deep link", async () => {
    await bound();
    fetcher.mockResolvedValueOnce(probe("another-account"));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9090 });
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login", { replace: true });
  });

  it("sends a page the server names as superseded (9090) to sign-in, not to its deep link", async () => {
    await bound();
    fetcher.mockResolvedValueOnce(refusal(9090));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9090 });
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login", { replace: true });
  });

  it("resumes an expired session at the same page, query and fragment", async () => {
    window.history.replaceState({}, "", "/spaces/x?a=1#section");
    await bound();
    fetcher.mockResolvedValueOnce(refusal(9005));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ code: 9090 });
    expect(navigate).toHaveBeenCalledExactlyOnceWith(
      "/login?next=%2Fspaces%2Fx%3Fa%3D1%23section",
      { replace: true }
    );
  });

  it("navigates once for concurrent refusals and remains blocked when navigation returns", async () => {
    await bound();
    await Promise.allSettled([
      owner.handleRefusal(refusal(9090), "/api"),
      owner.handleRefusal(refusal(9090), "/api")
    ]);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(owner.getSessionSnapshot().status).toBe("stale");
    await expect(owner.handleRefusal(probe(), "/api")).rejects.toMatchObject({ code: 9090 });
    owner.reloadSession();
    expect(navigate).toHaveBeenLastCalledWith("/login", { replace: true });
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
    fetcher.mockResolvedValueOnce(refusal(undefined, 503));
    await expect(owner.checkBrowserSession()).rejects.toMatchObject({ status: 503 });
    expect(navigate).not.toHaveBeenCalled();
    // The next request checks again and goes once the server answers for this session.
    fetcher.mockClear();
    await expect(
      owner.prepareBrowserRequest(new Request("https://eneo.test/api"))
    ).resolves.toBeInstanceOf(Request);
    expect(fetcher).toHaveBeenCalledExactlyOnceWith("/api/v1/auth/session/", expect.anything());
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

  it("checks the session again when the browser is back online after a check failed offline", async () => {
    await bound();
    // Work the browser's return sets off, listening before the session does.
    let work: Promise<Request> | undefined;
    const resend = () => {
      work = owner.prepareBrowserRequest(new Request("https://eneo.test/api", { method: "POST" }));
    };
    window.addEventListener("online", resend);
    const stop = owner.listenForSessionResume();
    try {
      // Online without a failed check: nothing to check.
      window.dispatchEvent(new Event("online"));
      await work;
      expect(fetcher).not.toHaveBeenCalled();

      fetcher.mockRejectedValueOnce(new TypeError("Offline"));
      await expect(owner.checkBrowserSession()).rejects.toThrow("Offline");
      window.dispatchEvent(new Event("online"));
      await expect(work).resolves.toBeInstanceOf(Request);
      expect(fetcher).toHaveBeenCalledTimes(2);
      expect(owner.getSessionSnapshot()).not.toHaveProperty("checkError");
    } finally {
      stop();
      window.removeEventListener("online", resend);
    }
  });

  it("still ends the page when the check back online finds another person's session", async () => {
    await bound();
    const stop = owner.listenForSessionResume();
    try {
      fetcher.mockRejectedValueOnce(new TypeError("Offline"));
      await expect(owner.checkBrowserSession()).rejects.toThrow("Offline");
      fetcher.mockResolvedValueOnce(probe("another-person"));
      window.dispatchEvent(new Event("online"));
      await expect(
        owner.prepareBrowserRequest(new Request("https://eneo.test/api"))
      ).rejects.toBeDefined();
      expect(owner.getSessionSnapshot().status).toBe("stale");
      expect(navigate).toHaveBeenCalled();
    } finally {
      stop();
    }
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
    // In place of the protected page: Back after logout must not reopen it and
    // send the person to login again, so Back can leave Eneo.
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Fspaces%2Fx%3Fa%3D1", {
      replace: true
    });
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
    [9019, 403, "/deactivated"],
    [9025, 403, "/deactivated"],
    [9070, 403, "/password-change?next=%2Fspaces%2Fx%3Fa%3D1"]
  ])("routes %s/%s through a document load", async (code, status, destination) => {
    await bound();
    await expect(owner.handleRefusal(refusal(code, status), "/api")).rejects.toMatchObject({
      status
    });
    expect(navigate).toHaveBeenCalledExactlyOnceWith(destination, { replace: true });
  });

  it.each([9019, 9025])(
    "blocks an admitted document refused as restricted (%s) and names the restriction",
    async (code) => {
      await bound();
      await expect(
        owner.handleRefusal(refusal(code, 403), "/api/v1/users/me/")
      ).rejects.toMatchObject({ status: 403, code });
      expect(owner.getSessionSnapshot()).toEqual({
        status: "stale",
        destination: "/deactivated",
        restriction: code
      });
      expect(clear).toHaveBeenCalledTimes(1);
      await expect(
        owner.prepareBrowserRequest(new Request("https://eneo.test/api", { method: "POST" }))
      ).rejects.toMatchObject({ code: 9090 });
      expect(fetcher).not.toHaveBeenCalled();
    }
  );

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

describe("checking again after a failed check", () => {
  afterEach(() => vi.restoreAllMocks());
  const failures = [
    ["the connection was lost", () => Promise.reject(new TypeError("Offline"))],
    ["the server answered 503", () => Promise.resolve(refusal(undefined, 503))]
  ] as const;
  /** A bound page whose last check failed with `answer`. */
  async function failedCheck(answer: () => Promise<Response>): Promise<unknown> {
    await bound();
    fetcher.mockImplementationOnce(answer);
    const failure = await owner.checkBrowserSession().catch((error: unknown) => error);
    expect(owner.getSessionSnapshot()).toMatchObject({ status: "bound", checkError: failure });
    fetcher.mockClear();
    return failure;
  }
  const prepare = () => owner.prepareBrowserRequest(new Request("https://eneo.test/api"));

  it.each(failures)(
    "checks once again for requests prepared together after %s",
    async (_, answer) => {
      await failedCheck(answer);
      const requests = await Promise.all([prepare(), prepare()]);
      expect(requests.map((request) => request.headers.get(GENERATION))).toEqual([
        "document-session",
        "document-session"
      ]);
      expect(fetcher).toHaveBeenCalledExactlyOnceWith("/api/v1/auth/session/", expect.anything());
      expect(owner.getSessionSnapshot()).toEqual({
        status: "bound",
        generation: "document-session"
      });
    }
  );

  it.each(failures)(
    "refuses a request at once while the browser is offline after %s",
    async (_, answer) => {
      const failure = await failedCheck(answer);
      vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
      await expect(prepare()).rejects.toBe(failure);
      expect(fetcher).not.toHaveBeenCalled();
    }
  );

  it.each([403, 429])(
    "does not check again for a request after a %i refusal, but still does when the tab is shown",
    async (status) => {
      await bound();
      fetcher.mockResolvedValueOnce(refusal(undefined, status));
      const refused = await owner.checkBrowserSession().catch((error: unknown) => error);
      expect(refused).toMatchObject({ status });
      fetcher.mockClear();
      await expect(prepare()).rejects.toBe(refused);
      expect(fetcher).not.toHaveBeenCalled();
      const stop = owner.listenForSessionResume();
      try {
        document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
        expect(fetcher).toHaveBeenCalledTimes(1);
        await owner.checkBrowserSession();
        expect(fetcher).toHaveBeenCalledTimes(1);
      } finally {
        stop();
      }
    }
  );

  it("checks again once per request and refuses it with that check's failure", async () => {
    await failedCheck(() => Promise.reject(new TypeError("Offline")));
    const still = new TypeError("Still offline");
    // Two answers only: a third check would get a success and fail the counts below.
    fetcher.mockRejectedValueOnce(still).mockRejectedValueOnce(still);
    await expect(prepare()).rejects.toBe(still);
    await expect(prepare()).rejects.toBe(still);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(owner.getSessionSnapshot()).toMatchObject({ status: "bound", checkError: still });
  });

  it.each([
    ["another person signed in", () => probe("another-account"), "/login"],
    ["the server names the session superseded", () => refusal(9090), "/login"],
    ["the session expired", () => refusal(9005), "/login?next=%2Fspaces%2Fx%3Fa%3D1"],
    ["the account is inactive", () => refusal(9019, 403), "/deactivated"],
    ["the organisation is deactivated", () => refusal(9025, 403), "/deactivated"]
  ])("ends the page as any check does when, checked again, %s", async (_, answer, destination) => {
    await failedCheck(() => Promise.reject(new TypeError("Offline")));
    fetcher.mockResolvedValueOnce(answer());
    await expect(prepare()).rejects.toThrow();
    expect(navigate).toHaveBeenCalledExactlyOnceWith(destination, { replace: true });
    expect(owner.getSessionSnapshot()).toMatchObject({ status: "stale", destination });
  });

  it("gives every request waiting on the new check the same refusal", async () => {
    await failedCheck(() => Promise.resolve(refusal(undefined, 503)));
    fetcher.mockResolvedValueOnce(refusal(9019, 403));
    const [first, second] = await Promise.allSettled([prepare(), prepare()]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(first).toMatchObject({ status: "rejected", reason: { status: 403, code: 9019 } });
    expect((second as PromiseRejectedResult).reason).toBe((first as PromiseRejectedResult).reason);
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/deactivated", { replace: true });
  });

  it("lets a session that must change its password through, then the request's refusal sends it there", async () => {
    await failedCheck(() => Promise.reject(new TypeError("Offline")));
    // The server answers the session check before the password is changed.
    const request = await prepare();
    expect(request.headers.get(GENERATION)).toBe("document-session");
    expect(fetcher).toHaveBeenCalledTimes(1);
    await expect(owner.handleRefusal(refusal(9070, 403), request.url)).rejects.toMatchObject({
      status: 403,
      code: 9070
    });
    expect(navigate).toHaveBeenCalledExactlyOnceWith(
      "/password-change?next=%2Fspaces%2Fx%3Fa%3D1",
      { replace: true }
    );
  });
});

describe("session expiry and renewal", () => {
  const EXPIRES_IN = "Eneo-Session-Expires-In";
  const LIFETIME = "Eneo-Session-Lifetime";
  const timedProbe = (seconds: string, lifetime?: string) =>
    new Response(null, {
      status: 204,
      headers: {
        [GENERATION]: "document-session",
        [EXPIRES_IN]: seconds,
        ...(lifetime ? { [LIFETIME]: lifetime } : {})
      }
    });
  // A renewal keeps the session's generation.
  const renewed = () =>
    Response.json(
      { generation: "document-session", expires_in: 86_400 },
      { headers: { [GENERATION]: "document-session" } }
    );
  /** Whether a promise has settled, after pending callbacks have run. */
  const settled = async (promise: Promise<unknown>) => {
    let done = false;
    void promise.then(
      () => (done = true),
      () => (done = true)
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    return done;
  };

  class FakeChannel extends EventTarget {
    static all: FakeChannel[] = [];
    posted: unknown[] = [];
    constructor(readonly name: string) {
      super();
      FakeChannel.all.push(this);
    }
    postMessage(data: unknown) {
      this.posted.push(data);
    }
    close() {}
  }
  const deliver = (data: unknown) =>
    FakeChannel.all.forEach((channel) =>
      channel.dispatchEvent(new MessageEvent("message", { data }))
    );

  beforeEach(() => {
    vi.useFakeTimers({ now: new Date("2026-11-02T10:00:00Z"), toFake: ["Date"] });
    FakeChannel.all = [];
    vi.stubGlobal("BroadcastChannel", FakeChannel);
  });
  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(navigator, "locks");
  });

  it("binds the session with the time it has left and the lifetime it was issued for", async () => {
    // A ten-minute session, reopened with half a minute left.
    fetcher.mockResolvedValueOnce(timedProbe("30", "600"));
    await owner.initializeBrowserSession();
    expect(owner.getSessionSnapshot()).toEqual({
      status: "bound",
      generation: "document-session",
      expiresAt: Date.now() + 30_000,
      lifetime: 600_000
    });
  });

  it("keeps no expiry without the header and re-bases it on every resume check", async () => {
    await owner.initializeBrowserSession();
    expect(owner.getSessionSnapshot()).toEqual({ status: "bound", generation: "document-session" });
    // The device slept for an hour; the check after it decides what is left.
    vi.setSystemTime(Date.now() + 3_600_000);
    fetcher.mockResolvedValueOnce(timedProbe("60", "86400"));
    await owner.checkBrowserSession();
    expect(owner.getSessionSnapshot()).toEqual({
      status: "bound",
      generation: "document-session",
      expiresAt: Date.now() + 60_000,
      lifetime: 86_400_000
    });
  });

  it("never takes the time left for the lifetime when the server does not say it", async () => {
    fetcher.mockResolvedValueOnce(timedProbe("60"));
    await owner.initializeBrowserSession();
    expect(owner.getSessionSnapshot()).toEqual({
      status: "bound",
      generation: "document-session",
      expiresAt: Date.now() + 60_000
    });
  });

  it("renews with the document's generation, takes the new end and holds other requests until then", async () => {
    await bound();
    let answer!: (response: Response) => void;
    fetcher.mockReturnValueOnce(new Promise<Response>((resolve) => (answer = resolve)));

    const renewal = owner.extendBrowserSession();
    const held = owner.prepareBrowserRequest(
      new Request("https://eneo.test/api", { method: "POST" })
    );
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe("/api/v1/auth/session/extend/");
    expect(init).toMatchObject({ method: "POST", credentials: "same-origin", cache: "no-store" });
    expect(new Headers(init!.headers).get(GENERATION)).toBe("document-session");
    expect(await settled(held)).toBe(false);
    answer(renewed());
    await renewal;

    // The session keeps its generation; only its end moves.
    expect((await held).headers.get(GENERATION)).toBe("document-session");
    const expiresAt = Date.now() + 86_400_000;
    expect(owner.getSessionSnapshot()).toEqual({
      status: "bound",
      generation: "document-session",
      expiresAt,
      lifetime: 86_400_000
    });
    // Other tabs hear only which session was renewed, and when it now ends.
    expect(FakeChannel.all.map((channel) => channel.name)).toEqual(["eneo-session"]);
    expect(FakeChannel.all[0]!.posted).toEqual([{ generation: "document-session", expiresAt }]);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("holds requests until the renewal even when a resume check was already running", async () => {
    await bound();
    let finishCheck!: (response: Response) => void;
    let answer!: (response: Response) => void;
    fetcher
      .mockReturnValueOnce(new Promise<Response>((resolve) => (finishCheck = resolve)))
      .mockReturnValueOnce(new Promise<Response>((resolve) => (answer = resolve)));

    const checking = owner.checkBrowserSession();
    // Already waiting for the check when the renewal takes over.
    const held = owner.prepareBrowserRequest(new Request("https://eneo.test/api"));
    const renewal = owner.extendBrowserSession();
    finishCheck(probe());
    await checking;
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    // The check that settled first must not release requests the renewal holds.
    expect(await settled(held)).toBe(false);
    answer(renewed());
    await renewal;
    expect(await settled(held)).toBe(true);
  });

  it(
    "holds nothing once a check, a failed check or a renewal that took over has ended",
    { timeout: 2000 },
    async () => {
      await bound();
      // A new check asks the server only when nothing holds requests any more.
      const released = async () => {
        fetcher.mockClear();
        await owner.checkBrowserSession();
        expect(fetcher).toHaveBeenCalledTimes(1);
      };
      await owner.checkBrowserSession();
      await released();
      fetcher.mockRejectedValueOnce(new TypeError("Offline"));
      await expect(owner.checkBrowserSession()).rejects.toThrow("Offline");
      await released();
      let finishCheck!: (response: Response) => void;
      fetcher
        .mockReturnValueOnce(new Promise<Response>((resolve) => (finishCheck = resolve)))
        .mockResolvedValueOnce(renewed());
      const checking = owner.checkBrowserSession();
      const renewal = owner.extendBrowserSession();
      finishCheck(probe());
      await Promise.all([checking, renewal]);
      await released();
      expect(await settled(owner.prepareBrowserRequest(new Request("https://eneo.test/api")))).toBe(
        true
      );
    }
  );

  it("loses nothing when the renewal's answer is lost after the server changed the cookie", async () => {
    await bound();
    // The server renewed the session and set the new cookie; its answer never arrived.
    fetcher.mockRejectedValueOnce(new TypeError("Network"));
    await expect(owner.extendBrowserSession()).rejects.toThrow("Network");

    // The next request names the page's session, and the answer under the new
    // cookie names the same one: no reload, nothing cleared.
    const next = await owner.prepareBrowserRequest(
      new Request("https://eneo.test/api/v1/spaces/", { method: "POST" })
    );
    expect(next.headers.get(GENERATION)).toBe("document-session");
    await owner.handleRefusal(probe("document-session"), "/api/v1/spaces/");
    expect(owner.getSessionSnapshot()).toEqual({ status: "bound", generation: "document-session" });
    expect(navigate).not.toHaveBeenCalled();
    expect(clear).not.toHaveBeenCalled();
    // Another sign-in is still a change of identity.
    await expect(owner.handleRefusal(probe("someone-else"), "/api/v1/spaces/")).rejects.toThrow();
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login", { replace: true });
  });

  it.each([
    [401, 9005, "/login?next=%2Fspaces%2Fx%3Fa%3D1"],
    // Another sign-in holds the cookie: never this page's deep link.
    [401, 9090, "/login"],
    [403, 9019, "/deactivated"]
  ])(
    "ends the document as any refusal does when renewal answers %i (%i)",
    async (status, code, to) => {
      await bound();
      fetcher.mockResolvedValueOnce(refusal(code, status));
      await expect(owner.extendBrowserSession()).rejects.toMatchObject({ status, code });
      expect(owner.getSessionSnapshot().status).toBe("stale");
      expect(navigate).toHaveBeenCalledExactlyOnceWith(to, { replace: true });
      expect(FakeChannel.all.flatMap((channel) => channel.posted)).toEqual([]);
    }
  );

  it("keeps the session as it was when renewal fails for another reason", async () => {
    await bound();
    fetcher.mockResolvedValueOnce(refusal(undefined, 500));
    await expect(owner.extendBrowserSession()).rejects.toMatchObject({ status: 500 });
    // It answered, so the cookie is the one it had; nothing else is asked.
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(owner.getSessionSnapshot()).toEqual({ status: "bound", generation: "document-session" });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("never applies a renewal whose answer is read after another sign-in ended the page", async () => {
    await bound();
    let reading!: () => void;
    const started = new Promise<void>((resolve) => (reading = resolve));
    let body!: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>(
      { start: (controller) => void (body = controller), pull: () => reading() },
      { highWaterMark: 0 }
    );
    fetcher.mockResolvedValueOnce(
      new Response(stream, {
        headers: { "content-type": "application/json", [GENERATION]: "document-session" }
      })
    );

    const renewal = owner.extendBrowserSession().catch((reason: unknown) => reason);
    await started;
    // Another request is refused: another person's sign-in now holds the cookie.
    await expect(owner.handleRefusal(refusal(9090), "/api/v1/spaces/")).rejects.toMatchObject({
      code: 9090
    });
    body.enqueue(
      new TextEncoder().encode(
        JSON.stringify({ generation: "document-session", expires_in: 86_400 })
      )
    );
    body.close();

    expect(await renewal).toMatchObject({ name: "EneoApiError", status: 401, code: 9090 });
    expect(owner.getSessionSnapshot()).toEqual({ status: "stale", destination: "/login" });
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login", { replace: true });
    expect(FakeChannel.all.flatMap((channel) => channel.posted)).toEqual([]);
  });

  const sessionNow = (generation: string, seconds: string) =>
    new Response(null, {
      status: 204,
      headers: { [GENERATION]: generation, [EXPIRES_IN]: seconds }
    });

  it.each([
    [
      "its answer cannot be read",
      () =>
        Promise.resolve(new Response("<html>", { headers: { [GENERATION]: "document-session" } }))
    ],
    ["the connection drops", () => Promise.reject(new TypeError("Network"))]
  ])("keeps the page and its session for a retry when %s", async (_, answer) => {
    await bound();
    // Whatever the cookie now holds, this page cannot prove it is its own.
    fetcher
      .mockImplementationOnce(answer)
      .mockResolvedValue(sessionNow("renewed-session", "86400"));

    await expect(owner.extendBrowserSession()).rejects.toThrow();

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(owner.getSessionSnapshot()).toEqual({ status: "bound", generation: "document-session" });
    expect(FakeChannel.all.flatMap((channel) => channel.posted)).toEqual([]);
    expect(navigate).not.toHaveBeenCalled();
    fetcher.mockResolvedValueOnce(renewed());
    await owner.extendBrowserSession();
    expect(new Headers(fetcher.mock.calls[1]![1]!.headers).get(GENERATION)).toBe(
      "document-session"
    );
    expect(owner.getSessionSnapshot()).toMatchObject({
      generation: "document-session",
      expiresAt: Date.now() + 86_400_000
    });
  });

  it("never sends a waiting write as another account after a renewal's answer is lost", async () => {
    await bound();
    let lose!: (error: Error) => void;
    fetcher
      .mockReturnValueOnce(new Promise<Response>((_, reject) => (lose = reject)))
      // Meanwhile another tab signed in to another account: the cookie names it.
      .mockResolvedValue(sessionNow("another-account", "86400"));

    const renewal = owner.extendBrowserSession();
    const write = owner.prepareBrowserRequest(
      new Request("https://eneo.test/api", { method: "POST" })
    );
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    lose(new TypeError("Network"));
    await expect(renewal).rejects.toThrow("Network");
    await expect(write).rejects.toThrow("Network");

    // Sent again, the write still speaks for this page's account; the server
    // refuses it as superseded, which is the page's way to sign in again.
    const again = await owner.prepareBrowserRequest(
      new Request("https://eneo.test/api", { method: "POST" })
    );
    expect(again.headers.get(GENERATION)).toBe("document-session");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(FakeChannel.all.flatMap((channel) => channel.posted)).toEqual([]);
  });

  it("follows another tab's renewal only when bound to the session it renewed", async () => {
    fetcher.mockResolvedValueOnce(timedProbe("100"));
    await owner.initializeBrowserSession();
    const stop = owner.listenForSessionResume();
    const before = Date.now() + 100_000;
    const expiresAt = Date.now() + 86_400_000;

    deliver({ generation: "someone-elses-session", expiresAt });
    expect(owner.getSessionSnapshot()).toMatchObject({ expiresAt: before });
    deliver({ generation: "document-session", expiresAt });
    expect(owner.getSessionSnapshot()).toEqual({
      status: "bound",
      generation: "document-session",
      expiresAt,
      lifetime: 86_400_000
    });

    stop();
    deliver({ generation: "document-session", expiresAt: expiresAt + 1 });
    expect(owner.getSessionSnapshot()).toMatchObject({ expiresAt });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["names the session's old end", () => timedProbe("30")],
    ["is refused as superseded", () => refusal(9090)],
    ["fails", () => Promise.reject(new TypeError("Offline"))]
  ])("keeps another tab's renewal when a check that started before it %s", async (_, answer) => {
    await bound();
    const stop = owner.listenForSessionResume();
    let finishCheck!: (response: Response | Promise<Response>) => void;
    fetcher.mockReturnValueOnce(new Promise<Response>((resolve) => (finishCheck = resolve)));

    const checking = owner.checkBrowserSession();
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const expiresAt = Date.now() + 86_400_000;
    deliver({ generation: "document-session", expiresAt });
    finishCheck(answer());
    await checking.catch(() => {});

    const next = await owner.prepareBrowserRequest(new Request("https://eneo.test/api"));
    expect(next.headers.get(GENERATION)).toBe("document-session");
    expect(owner.getSessionSnapshot()).toEqual({
      status: "bound",
      generation: "document-session",
      expiresAt,
      lifetime: 86_400_000
    });
    expect(navigate).not.toHaveBeenCalled();
    stop();
  });

  it.each([
    [401, { message: "Token has expired", eneo_error_code: 9005 }],
    [401, { message: "The browser session changed", eneo_error_code: 9090 }],
    [403, { message: "The account is inactive.", eneo_error_code: 9019 }],
    [403, { message: "The password must be changed.", eneo_error_code: 9070 }]
  ])(
    "keeps another tab's renewal that arrives while a check reads its %i answer %j",
    async (status, error) => {
      await bound();
      const stop = owner.listenForSessionResume();
      let reading!: () => void;
      const started = new Promise<void>((resolve) => (reading = resolve));
      let body!: ReadableStreamDefaultController<Uint8Array>;
      const stream = new ReadableStream<Uint8Array>(
        {
          start: (controller) => void (body = controller),
          pull: () => reading()
        },
        { highWaterMark: 0 }
      );
      // The old session was refused; the check is still reading why.
      fetcher.mockResolvedValueOnce(
        new Response(stream, {
          status,
          headers: { "content-type": "application/json", [GENERATION]: "document-session" }
        })
      );

      const checking = owner.checkBrowserSession();
      await started;
      deliver({ generation: "document-session", expiresAt: Date.now() + 86_400_000 });
      body.enqueue(new TextEncoder().encode(JSON.stringify(error)));
      body.close();
      await checking.catch(() => {});

      // The refusal was about the token the renewal replaced.
      const next = await owner.prepareBrowserRequest(new Request("https://eneo.test/api"));
      expect(next.headers.get(GENERATION)).toBe("document-session");
      expect(owner.getSessionSnapshot().status).toBe("bound");
      expect(navigate).not.toHaveBeenCalled();
      expect(clear).not.toHaveBeenCalled();
      stop();
    }
  );

  it("holds a request whose new check a renewal takes over until the renewal answers", async () => {
    await bound();
    fetcher.mockRejectedValueOnce(new TypeError("Offline"));
    await expect(owner.checkBrowserSession()).rejects.toThrow("Offline");
    fetcher.mockClear();
    let finishCheck!: (response: Response) => void;
    let answer!: (response: Response) => void;
    fetcher
      .mockReturnValueOnce(new Promise<Response>((resolve) => (finishCheck = resolve)))
      .mockReturnValueOnce(new Promise<Response>((resolve) => (answer = resolve)));

    const held = owner.prepareBrowserRequest(new Request("https://eneo.test/api"));
    expect(fetcher).toHaveBeenCalledTimes(1);
    const renewal = owner.extendBrowserSession();
    finishCheck(probe());
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(await settled(held)).toBe(false);
    answer(renewed());
    await renewal;
    expect(await settled(held)).toBe(true);
  });

  it("refuses a request whose new check another tab's renewal ended unanswered", async () => {
    await bound();
    const stop = owner.listenForSessionResume();
    fetcher.mockResolvedValueOnce(refusal(undefined, 503));
    const failure = await owner.checkBrowserSession().catch((error: unknown) => error);
    let finishCheck!: (response: Response) => void;
    fetcher.mockReturnValueOnce(new Promise<Response>((resolve) => (finishCheck = resolve)));
    const request = owner
      .prepareBrowserRequest(new Request("https://eneo.test/api"))
      .catch((error: unknown) => error);
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    deliver({ generation: "document-session", expiresAt: Date.now() + 86_400_000 });
    // The answer may be about the token the renewal replaced: it is not applied.
    finishCheck(probe());
    expect(await request).toBe(failure);
    expect(owner.getSessionSnapshot()).toMatchObject({ status: "bound", checkError: failure });
    expect(navigate).not.toHaveBeenCalled();
    stop();
  });

  it.each([
    ["succeeds", () => Promise.resolve(probe())],
    ["fails", () => Promise.reject(new TypeError("Still offline"))]
  ])(
    "lets a request that joined a new check another tab's renewal ended go only when its own check %s",
    async (outcome, answer) => {
      await bound();
      const stop = owner.listenForSessionResume();
      fetcher.mockResolvedValueOnce(refusal(undefined, 503));
      const failure = await owner.checkBrowserSession().catch((error: unknown) => error);
      fetcher.mockClear();
      let finishCheck!: (response: Response) => void;
      fetcher
        .mockReturnValueOnce(new Promise<Response>((resolve) => (finishCheck = resolve)))
        .mockImplementationOnce(answer);
      const prepare = () =>
        owner
          .prepareBrowserRequest(new Request("https://eneo.test/api"))
          .catch((error: unknown) => error);
      // The first starts the new check; the second joins it.
      const starter = prepare();
      const joiner = prepare();
      await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
      deliver({ generation: "document-session", expiresAt: Date.now() + 86_400_000 });
      expect(await settled(joiner)).toBe(false);
      expect(fetcher).toHaveBeenCalledTimes(1);
      // The answer may be about the token the renewal replaced: it is not applied.
      finishCheck(probe());

      expect(await starter).toBe(failure);
      const joined = await joiner;
      // The joiner made its own check; nothing goes without one that succeeded.
      expect(fetcher).toHaveBeenCalledTimes(2);
      if (outcome === "succeeds") {
        expect((joined as Request).headers.get(GENERATION)).toBe("document-session");
        expect(owner.getSessionSnapshot()).not.toHaveProperty("checkError");
      } else {
        expect(joined).toMatchObject({ message: "Still offline" });
        expect(owner.getSessionSnapshot()).toMatchObject({ checkError: joined });
      }
      expect(navigate).not.toHaveBeenCalled();
      stop();
    }
  );

  it("does not renew again after waiting for another tab that already did", async () => {
    await bound();
    const stop = owner.listenForSessionResume();
    let release!: () => void;
    const request = vi.fn((_name: string, renew: () => Promise<void>) =>
      new Promise<void>((resolve) => (release = resolve)).then(renew)
    );
    Object.defineProperty(navigator, "locks", { value: { request }, configurable: true });

    const renewal = owner.extendBrowserSession();
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(request.mock.calls[0]![0]).toBe("eneo-session-extend");
    const expiresAt = Date.now() + 86_400_000;
    deliver({ generation: "document-session", expiresAt });
    release();
    await renewal;

    expect(fetcher).not.toHaveBeenCalled();
    expect(owner.getSessionSnapshot()).toMatchObject({ generation: "document-session", expiresAt });
    stop();
  });

  describe("time limit", () => {
    const LIMIT = 15_000;
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
    });

    /** A server that never answers: the request ends only when it is aborted. */
    const silent = (_: unknown, init?: RequestInit) =>
      new Promise<Response>((_, reject) => {
        const signal = init!.signal!;
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    /** A refusal naming another person's session (9090) whose body never arrives whole. */
    const cutOff = (lost?: Error) => (_: unknown, init?: RequestInit) => {
      const signal = init!.signal!;
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('{"message":"Refused","eneo_error_code":90'));
          if (lost) controller.error(lost);
          else
            signal.addEventListener("abort", () => controller.error(signal.reason), { once: true });
        }
      });
      return Promise.resolve(
        new Response(body, { status: 401, headers: { "content-type": "application/json" } })
      );
    };
    /** An answer whose body stops after its headers until the request is aborted. */
    const stalled = (status: number) => (_: unknown, init?: RequestInit) => {
      const signal = init!.signal!;
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          signal.addEventListener("abort", () => controller.error(signal.reason), { once: true });
        }
      });
      return Promise.resolve(
        new Response(body, {
          status,
          headers: { "content-type": "application/json", [GENERATION]: "document-session" }
        })
      );
    };
    /** Whether a promise has settled, once pending callbacks have run. */
    const done = async (promise: Promise<unknown>) => {
      let settled = false;
      void promise.then(
        () => (settled = true),
        () => (settled = true)
      );
      await vi.advanceTimersByTimeAsync(0);
      return settled;
    };
    const asks = [
      ["check", () => owner.checkBrowserSession()],
      ["renewal", () => owner.extendBrowserSession()]
    ] as const;

    it("gives up a check that has no answer at the limit and lets the next check start", async () => {
      await bound();
      fetcher.mockImplementationOnce(silent);
      const checking = owner.checkBrowserSession();
      await vi.advanceTimersByTimeAsync(LIMIT - 1);
      expect(await done(checking)).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      expect(await done(checking)).toBe(true);
      const error = await checking.catch((reason: unknown) => reason);
      expect(error).toMatchObject({ name: "EneoApiError", status: 504 });
      // Aborted, not raced: an answer that never came cannot arrive later.
      expect(fetcher.mock.calls[0]![1]!.signal!.aborted).toBe(true);
      expect(owner.getSessionSnapshot()).toEqual({
        status: "bound",
        generation: "document-session",
        checkError: error
      });
      // Nothing holds requests any more: the next check asks the server again.
      await owner.checkBrowserSession();
      expect(fetcher).toHaveBeenCalledTimes(2);
      await expect(
        owner.prepareBrowserRequest(new Request("https://eneo.test/api"))
      ).resolves.toBeInstanceOf(Request);
    });

    it("checks again for the next request after a check ran out of time", async () => {
      await bound();
      fetcher.mockImplementationOnce(silent);
      const checking = owner.checkBrowserSession().catch((reason: unknown) => reason);
      await vi.advanceTimersByTimeAsync(LIMIT);
      expect(await checking).toMatchObject({ name: "EneoApiError", status: 504 });
      await expect(
        owner.prepareBrowserRequest(new Request("https://eneo.test/api"))
      ).resolves.toBeInstanceOf(Request);
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it("gives up a renewal that has no answer at the limit and keeps the session for a retry", async () => {
      await bound();
      fetcher.mockImplementationOnce(silent);
      const renewal = owner.extendBrowserSession();
      const held = owner
        .prepareBrowserRequest(new Request("https://eneo.test/api", { method: "POST" }))
        .catch((reason: unknown) => reason);
      await vi.advanceTimersByTimeAsync(0);
      expect(fetcher).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(LIMIT);
      expect(await done(renewal)).toBe(true);
      const error = await renewal.catch((reason: unknown) => reason);
      // Never an AbortError: streams do not reconnect after one.
      expect(error).toMatchObject({ name: "EneoApiError", status: 504 });
      expect(await held).toBe(error);
      expect(owner.getSessionSnapshot()).toEqual({
        status: "bound",
        generation: "document-session"
      });
      expect(FakeChannel.all.flatMap((channel) => channel.posted)).toEqual([]);
      expect(navigate).not.toHaveBeenCalled();
    });

    it.each([200, 500])(
      "gives up a %i renewal whose body stops after its headers, for it and the requests it holds",
      async (status) => {
        await bound();
        fetcher.mockRejectedValueOnce(new TypeError("Offline"));
        const failure = await owner.checkBrowserSession().catch((reason: unknown) => reason);
        fetcher.mockImplementationOnce(stalled(status));
        const renewal = owner.extendBrowserSession().catch((reason: unknown) => reason);
        const held = owner
          .prepareBrowserRequest(new Request("https://eneo.test/api", { method: "POST" }))
          .catch((reason: unknown) => reason);
        await vi.advanceTimersByTimeAsync(LIMIT - 1);
        expect(await done(renewal)).toBe(false);
        await vi.advanceTimersByTimeAsync(1);
        expect(await done(renewal)).toBe(true);
        const error = await renewal;
        expect(error).toMatchObject({ name: "EneoApiError", status: 504 });
        expect(await held).toBe(error);
        expect(fetcher).toHaveBeenCalledTimes(2);
        // The renewal changed nothing: the earlier failure still stands.
        expect(owner.getSessionSnapshot()).toEqual({
          status: "bound",
          generation: "document-session",
          checkError: failure
        });
        expect(FakeChannel.all.flatMap((channel) => channel.posted)).toEqual([]);
        expect(navigate).not.toHaveBeenCalled();
      }
    );

    it("never applies a renewal whose answer is read after the limit", async () => {
      await bound();
      // This body goes on after the abort, as a late answer would.
      let body!: ReadableStreamDefaultController<Uint8Array>;
      fetcher.mockResolvedValueOnce(
        new Response(
          new ReadableStream<Uint8Array>({ start: (controller) => void (body = controller) }),
          { headers: { "content-type": "application/json", [GENERATION]: "document-session" } }
        )
      );
      const renewal = owner.extendBrowserSession().catch((reason: unknown) => reason);
      await vi.advanceTimersByTimeAsync(LIMIT);
      body.enqueue(
        new TextEncoder().encode(
          JSON.stringify({ generation: "document-session", expires_in: 86_400 })
        )
      );
      body.close();
      expect(await done(renewal)).toBe(true);
      expect(await renewal).toMatchObject({ name: "EneoApiError", status: 504 });
      expect(owner.getSessionSnapshot()).toEqual({
        status: "bound",
        generation: "document-session"
      });
      expect(FakeChannel.all.flatMap((channel) => channel.posted)).toEqual([]);
    });

    it.each(asks)(
      "still ends the page on a whole %s refusal for another sign-in read after the limit",
      async (_, ask) => {
        await bound();
        // The refusal arrived whole; only reading its body ends after the limit.
        let body!: ReadableStreamDefaultController<Uint8Array>;
        fetcher.mockResolvedValueOnce(
          new Response(
            new ReadableStream<Uint8Array>({ start: (controller) => void (body = controller) }),
            { status: 401, headers: { "content-type": "application/json" } }
          )
        );
        const asking = ask().catch((reason: unknown) => reason);
        await vi.advanceTimersByTimeAsync(LIMIT);
        expect(await done(asking)).toBe(false);
        expect(fetcher.mock.calls[0]![1]!.signal!.aborted).toBe(true);
        expect(navigate).not.toHaveBeenCalled();
        body.enqueue(
          new TextEncoder().encode(JSON.stringify({ message: "Refused", eneo_error_code: 9090 }))
        );
        body.close();
        expect(await done(asking)).toBe(true);
        const error = await asking;
        expect(error).toMatchObject({ name: "EneoApiError", status: 401, code: 9090 });
        expect(navigate).toHaveBeenCalledExactlyOnceWith("/login", { replace: true });
        expect(owner.getSessionSnapshot()).toEqual({ status: "stale", destination: "/login" });
      }
    );

    it("aborts a running check when the page ends, and not as a time-out", async () => {
      await bound();
      fetcher.mockImplementationOnce(silent);
      const checking = owner.checkBrowserSession().catch((reason: unknown) => reason);
      await vi.advanceTimersByTimeAsync(0);
      expect(fetcher).toHaveBeenCalledTimes(1);
      await expect(owner.handleRefusal(refusal(9090), "/api/v1/spaces/")).rejects.toMatchObject({
        code: 9090
      });
      expect(await done(checking)).toBe(true);
      expect(fetcher.mock.calls[0]![1]!.signal!.aborted).toBe(true);
      const error = await checking;
      expect(error).toMatchObject({ name: "AbortError" });
      expect(error).not.toMatchObject({ status: 504 });
      expect(owner.getSessionSnapshot()).toEqual({ status: "stale", destination: "/login" });
    });

    it.each(asks)("never takes a %s refusal the limit cut off for an expiry", async (_, ask) => {
      await bound();
      fetcher.mockImplementationOnce(cutOff());
      const asking = ask();
      await vi.advanceTimersByTimeAsync(0);
      expect(fetcher).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(LIMIT);
      expect(await done(asking)).toBe(true);
      await expect(asking).rejects.toMatchObject({ name: "EneoApiError", status: 504 });
      expect(navigate).not.toHaveBeenCalled();
      expect(owner.getSessionSnapshot()).toMatchObject({
        status: "bound",
        generation: "document-session"
      });
      expect(FakeChannel.all.flatMap((channel) => channel.posted)).toEqual([]);
    });

    it.each(asks)(
      "never takes a %s refusal a lost connection cut off for an expiry",
      async (_, ask) => {
        await bound();
        fetcher.mockImplementationOnce(cutOff(new TypeError("network error")));
        await expect(ask()).rejects.toThrow("network error");
        expect(navigate).not.toHaveBeenCalled();
        expect(owner.getSessionSnapshot()).toMatchObject({
          status: "bound",
          generation: "document-session"
        });
      }
    );

    it.each([
      ...asks.map(([kind, ask]) => [kind, ask, ""] as const),
      ...asks.map(([kind, ask]) => [kind, ask, "<html>"] as const)
    ])("still takes a %s refusal whose whole body is %j for an expiry", async (_, ask, body) => {
      await bound();
      fetcher.mockResolvedValueOnce(new Response(body, { status: 401 }));
      await expect(ask()).rejects.toMatchObject({ status: 401 });
      expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Fspaces%2Fx%3Fa%3D1", {
        replace: true
      });
    });
  });
});
