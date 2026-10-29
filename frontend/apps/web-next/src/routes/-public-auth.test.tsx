// @vitest-environment jsdom
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { createTranslator } from "use-intl";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/navigate-to", () => ({ navigateTo: navigate }));
const GENERATION = "Eneo-Session-Generation";
let generation: string | null;
let bootstrapRefusal: Response | undefined;
let replies: Map<string, unknown>;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  sessionStorage.clear();
  generation = null;
  bootstrapRefusal = undefined;
  replies = new Map<string, unknown>([
    [
      "/api/v1/auth/federation-status",
      {
        has_global_oidc_config: false,
        has_single_tenant_federation: false,
        has_multi_tenant_federation: false,
        tenant_count: 0
      }
    ],
    ["/api/v1/users/me/", { id: "user-a" }],
    ["/api/v1/auth/session/logout/", new Response(null, { status: 204 })]
  ]);
  fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = new URL(input instanceof Request ? input.url : String(input), window.location.href)
      .pathname;
    if (path === "/api/v1/auth/session/") {
      if (bootstrapRefusal) return bootstrapRefusal.clone();
      return generation
        ? new Response(null, { status: 204, headers: { [GENERATION]: generation } })
        : new Response(null, { status: 401 });
    }
    if (!replies.has(path)) throw new Error(`Unexpected request: ${path}`);
    const reply = await replies.get(path);
    if (reply instanceof Response) return reply.clone();
    return Response.json(reply, {
      headers: generation && !path.startsWith("/api/v1/auth/") ? { [GENERATION]: generation } : {}
    });
  });
  vi.stubGlobal("fetch", fetcher);
  vi.doMock("@/lib/navigation", () => import("@/lib/navigation.tanstack"));
  vi.doMock("@/lib/link", () => import("@/lib/link.tanstack"));
  vi.doMock("@/lib/api/base", async () => ({
    ...(await import("@/lib/api/base.vite")),
    API_BASE: window.location.origin
  }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function route(path: string, mount = true) {
  window.history.replaceState({}, "", path);
  const { getQueryClient } = await import("@/lib/api/query");
  const queryClient = getQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  const { setRuntimeConfig } = await import("@/lib/runtime-config");
  setRuntimeConfig({
    version: "1",
    revision: "test",
    help_center_url: null,
    legacy_app_url: null,
    accessibility_statement_url: "/statement",
    request_integration_form_url: null,
    mcp_app_content_origin: null,
    federation_enabled: false
  });
  const owner = await import("@/lib/api/refusal");
  await owner.initializeBrowserSession();
  const { createAppRouter } = await import("@/router");
  const { BootContext } = await import("@/boot-context");
  const router = createAppRouter(
    { queryClient, t: createTranslator({ locale: "sv", messages }) },
    { history: createMemoryHistory({ initialEntries: [path] }) }
  );
  if (mount) {
    render(
      <StrictMode>
        <BootContext value={{ locale: "sv", messages, nonce: undefined }}>
          <RouterProvider router={router} />
        </BootContext>
      </StrictMode>
    );
    await act(() => router.load());
  }
  return router;
}

function callsTo(path: string) {
  return fetcher.mock.calls.filter(
    ([input]) =>
      new URL(input instanceof Request ? input.url : String(input), window.location.href)
        .pathname === path
  );
}

it.each(["expired", "logout", "password_changed"])(
  "renders the %s notice without re-probing an anonymous identity",
  async (message) => {
    await route(`/login?message=${message}`);
    expect(await screen.findByRole("button", { name: messages.login })).toBeTruthy();
    const notice =
      message === "expired"
        ? messages.session_expired_please_login_again
        : message === "logout"
          ? messages.logout_success
          : messages.password_changed_login_again;
    expect(screen.getByText(notice)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: messages.a11y_statement_link }).getAttribute("href")
    ).toBe("/statement");
    expect(callsTo("/api/v1/auth/session/")).toHaveLength(1);
    expect(callsTo("/api/v1/users/me/")).toHaveLength(0);
    expect(navigate).not.toHaveBeenCalled();
    await expectNoAxeViolations();
  }
);

it("shows diagnostics as text and keeps a safe retry continuation", async () => {
  await route(
    "/login/failed?detailCode=access_denied&rawDetail=%3Cscript%3Ealert(1)%3C%2Fscript%3E&next=%2Fadmin"
  );
  expect(await screen.findByText(messages.oidc_error_forbidden)).toBeTruthy();
  expect(
    screen.getByRole("link", { name: messages.try_logging_in_again }).getAttribute("href")
  ).toBe("/login?next=%2Fadmin");
  expect(document.querySelector("main script")).toBeNull();
  expect(callsTo("/api/v1/users/me/")).toHaveLength(0);
});

it("shows the failed-login fallback", async () => {
  await route("/login/failed");
  expect(await screen.findByText(messages.failed_to_login)).toBeTruthy();
});

it("uses a document link for global SSO, without an app-router preload or interception", async () => {
  replies.set("/api/v1/auth/federation-status", { has_global_oidc_config: true });
  const router = await route("/login?message=logout&next=%2Fadmin");
  const link = await screen.findByRole("link", { name: messages.login_with_sso });
  expect(link.getAttribute("href")).toBe("/api/v1/auth/browser/initiate?next=%2Fadmin");
  expect(link.closest("form")).toBeNull();
  fireEvent.mouseEnter(link);
  expect(callsTo("/api/v1/auth/browser/initiate")).toHaveLength(0);
  // A cancelled native click still reaches no SPA navigation handler.
  const event = new MouseEvent("click", { bubbles: true, cancelable: true });
  let intercepted: boolean | undefined;
  const handler = (e: MouseEvent) => {
    intercepted = e.defaultPrevented;
    e.preventDefault();
  };
  document.addEventListener("click", handler, { once: true });
  fireEvent(link, event);
  expect(intercepted).toBe(false);
  expect(router.state.location.pathname).toBe("/login");
});

it.each(["has_global_oidc_config", "has_single_tenant_federation"])(
  "starts %s once after mount and hides password fields",
  async (flag) => {
    replies.set("/api/v1/auth/federation-status", { [flag]: true });
    await route("/login?next=%2Fspaces%2Fx%3Fa%3D1");
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledExactlyOnceWith(
        "/api/v1/auth/browser/initiate?next=%2Fspaces%2Fx%3Fa%3D1"
      )
    );
    expect(screen.queryByLabelText(messages.password, { exact: true })).toBeNull();
    expect(screen.getByText(messages.redirecting_to_authentication)).toBeTruthy();
  }
);

it("keeps explicit password login available on an SSO installation", async () => {
  replies.set("/api/v1/auth/federation-status", { has_single_tenant_federation: true });
  await route("/login?showUsernameAndPassword=true&next=%2Fadmin");
  expect(await screen.findByRole("button", { name: messages.login })).toBeTruthy();
  expect(screen.getByRole("link", { name: messages.hide_login_fields }).getAttribute("href")).toBe(
    "/login?next=%2Fadmin"
  );
  expect(navigate).not.toHaveBeenCalled();
});

it("does not flash password fields while SSO discovery is pending", async () => {
  let resolve!: (value: unknown) => void;
  replies.set(
    "/api/v1/auth/federation-status",
    new Promise((done) => {
      resolve = done;
    })
  );
  await route("/login");
  expect(screen.queryByRole("button", { name: messages.login })).toBeNull();
  await act(async () => resolve({ has_global_oidc_config: true }));
  await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("button", { name: messages.login })).toBeNull();
});

it.each([
  "message=logout",
  "message=oidc_callback_failed",
  "error=access_denied",
  "detailCode=access_denied"
])("does not auto-start SSO after %s", async (search) => {
  replies.set("/api/v1/auth/federation-status", { has_global_oidc_config: true });
  await route(`/login?${search}`);
  expect(await screen.findByRole("link", { name: messages.login_with_sso })).toBeTruthy();
  expect(screen.queryByRole("button", { name: messages.login })).toBeNull();
  expect(screen.getByRole("link", { name: messages.show_login_fields })).toBeTruthy();
  expect(navigate).not.toHaveBeenCalled();
});

function multiTenant() {
  replies.set("/api/v1/auth/federation-status", { has_multi_tenant_federation: true });
  replies.set("/api/v1/auth/tenants", {
    tenants: [
      { slug: "first", name: "First" },
      { slug: "second", name: "Second" }
    ]
  });
}

it("starts and remembers an explicit tenant once with a safe continuation", async () => {
  multiTenant();
  await route("/login?tenant=second&next=%2Fadmin");
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/auth/browser/initiate?tenant=second&next=%2Fadmin"
    )
  );
  expect(sessionStorage.getItem("eneo-last-tenant-slug")).toBe("second");
});

it("starts a valid explicit tenant without depending on the public selector request", async () => {
  multiTenant();
  replies.set("/api/v1/auth/tenants", new Response(null, { status: 503 }));
  await route("/login?tenant=second");
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/api/v1/auth/browser/initiate?tenant=second")
  );
  expect(callsTo("/api/v1/auth/tenants")).toHaveLength(0);
});

it.each(["invalid%2Fslug", "first&tenant=second"])(
  "ignores invalid tenant %s and shows choices instead of a remembered tenant",
  async (tenant) => {
    multiTenant();
    sessionStorage.setItem("eneo-last-tenant-slug", "first");
    await route(`/login?tenant=${tenant}`);
    expect(await screen.findByRole("link", { name: "Second" })).toBeTruthy();
    expect(navigate).not.toHaveBeenCalled();
  }
);

it("retries the callback's remembered tenant or clears it to choose another organisation", async () => {
  multiTenant();
  sessionStorage.setItem("eneo-last-tenant-slug", "first");
  const router = await route(
    "/login?tenant=first&message=oidc_callback_failed&info=old-failure&next=%2Fadmin"
  );
  const retry = await screen.findByRole("link", { name: messages.oidc_retry_login });
  expect(retry.getAttribute("href")).toBe(
    "/api/v1/auth/browser/initiate?tenant=first&next=%2Fadmin"
  );
  expect(navigate).not.toHaveBeenCalled();
  const chooseAnother = screen.getByRole("button", { name: messages.oidc_choose_another_org });
  chooseAnother.focus();
  fireEvent.click(chooseAnother);
  expect(sessionStorage.getItem("eneo-last-tenant-slug")).toBeNull();
  expect(await screen.findByRole("link", { name: "Second" })).toBeTruthy();
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByText(messages.select_your_organization))
  );
  await waitFor(() => expect(router.state.location.search).toEqual({ next: "/admin" }));
  expect(navigate).not.toHaveBeenCalled();
});

it("does not auto-select the sole tenant after a callback failure", async () => {
  replies.set("/api/v1/auth/federation-status", { has_multi_tenant_federation: true });
  replies.set("/api/v1/auth/tenants", { tenants: [{ slug: "first", name: "First" }] });
  await route("/login?message=oidc_callback_failed");
  expect(await screen.findByRole("link", { name: "First" })).toBeTruthy();
  expect(navigate).not.toHaveBeenCalled();
});

it("shows tenant choices instead of global SSO and remembers only the chosen organisation", async () => {
  replies.set("/api/v1/auth/federation-status", {
    has_multi_tenant_federation: true,
    has_global_oidc_config: true
  });
  replies.set("/api/v1/auth/tenants", {
    tenants: [
      { slug: "first", name: "First" },
      { slug: "second", name: "Second" }
    ]
  });
  sessionStorage.setItem("eneo-last-tenant-slug", "unknown");
  await route("/login");
  const link = await screen.findByRole("link", { name: "Second" });
  expect(link.getAttribute("href")).toBe("/api/v1/auth/browser/initiate?tenant=second");
  expect(screen.queryByRole("link", { name: messages.login_with_sso })).toBeNull();
  const request = callsTo("/api/v1/auth/tenants")[0]![0] as Request;
  expect(request.credentials).toBe("omit");
  expect(request.headers.has(GENERATION)).toBe(false);
  link.addEventListener("click", (e) => e.preventDefault());
  fireEvent.click(link);
  expect(sessionStorage.getItem("eneo-last-tenant-slug")).toBe("second");
});

it.each(["/admin", "//evil.example"])(
  "continues an admitted session to safe next %s only once",
  async (next) => {
    generation = "session-a";
    await route(`/login?${new URLSearchParams({ next })}`);
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledExactlyOnceWith(
        next === "/admin" ? next : "/spaces/personal/chat",
        { replace: true }
      )
    );
    const request = callsTo("/api/v1/users/me/")[0]![0] as Request;
    expect(request.headers.get(GENERATION)).toBe("session-a");
    expect(callsTo("/api/v1/users/me/")).toHaveLength(1);
  }
);

it.each([401, 503])("allows login after a %s /me refusal without a logout loop", async (status) => {
  generation = "session-a";
  replies.set("/api/v1/users/me/", new Response(null, { status }));
  await route("/login");
  expect(await screen.findByRole("button", { name: messages.login })).toBeTruthy();
  expect(navigate).not.toHaveBeenCalled();
});

it("never signs out or starts authentication while preloading", async () => {
  const router = await route("/login", false);
  fetcher.mockClear();
  await router.preloadRoute({ to: "/logout" });
  await router.preloadRoute({ to: "/login/switch-organisation" });
  await router.preloadRoute({ to: "/login", search: { tenant: "first" } });
  await router.preloadRoute({ to: "/deactivated" });
  await router.preloadRoute({ to: "/module-login" });
  await router.preloadRoute({ to: "/integrations/callback/token" });
  expect(fetcher).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
});

it("renders suspended-tenant recovery from the real root boot refusal", async () => {
  bootstrapRefusal = Response.json(
    { message: "Suspended", eneo_error_code: 9025 },
    { status: 403, headers: { [GENERATION]: "suspended" } }
  );
  await route("/deactivated");
  expect(
    await screen.findByRole("heading", { name: messages.organisation_deactivated })
  ).toBeTruthy();
  expect(screen.getByRole("link", { name: messages.logout }).getAttribute("href")).toBe("/logout");
  expect(screen.getByRole("link", { name: messages.retry }).getAttribute("href")).toBe(
    "/deactivated"
  );
  expect(callsTo("/api/v1/users/me/")).toHaveLength(0);
  expect(navigate).not.toHaveBeenCalled();
  await expectNoAxeViolations();
});

it("lets a fresh suspended logout document clear its unusable cookie once", async () => {
  bootstrapRefusal = Response.json(
    { message: "Suspended", eneo_error_code: 9025 },
    { status: 403, headers: { [GENERATION]: "suspended" } }
  );
  await route("/logout");
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?message=logout", { replace: true })
  );
  expect(callsTo("/api/v1/auth/session/logout/")).toHaveLength(1);
  expect(callsTo("/api/v1/auth/session/logout/")[0]![1]?.headers).toEqual({
    [GENERATION]: "suspended"
  });
  expect(callsTo("/api/v1/users/me/")).toHaveLength(0);
});

it("clears the expired cookie identified by bootstrap after a password change", async () => {
  bootstrapRefusal = Response.json(
    { message: "Expired", eneo_error_code: 9005 },
    { status: 401, headers: { [GENERATION]: "expired" } }
  );
  await route("/logout?reason=password_changed&next=%2Fadmin");
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith(
      "/login?message=password_changed&next=%2Fadmin",
      { replace: true }
    )
  );
  expect(callsTo("/api/v1/auth/session/logout/")).toHaveLength(1);
  expect(callsTo("/api/v1/auth/session/logout/")[0]![1]?.headers).toEqual({
    [GENERATION]: "expired"
  });
  expect(callsTo("/api/v1/users/me/")).toHaveLength(0);
});

it("self-heals an active organisation through a generation-bound read", async () => {
  generation = "reactivated";
  await route("/deactivated");
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/spaces/personal/chat", { replace: true })
  );
  const request = callsTo("/api/v1/users/me/")[0]![0] as Request;
  expect(request.headers.get(GENERATION)).toBe(generation);
});

it("returns a deactivated-page visitor with an expired session to login", async () => {
  generation = "expired-session";
  replies.set("/api/v1/users/me/", new Response(null, { status: 401 }));
  await route("/deactivated");
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login", { replace: true })
  );
});

it("shows a retryable read error when checking whether an organisation was reactivated", async () => {
  generation = "reactivated";
  const user = replies.get("/api/v1/users/me/");
  replies.set("/api/v1/users/me/", new Response(null, { status: 503 }));
  await route("/deactivated");
  const retry = await screen.findByRole("button", { name: /Försök igen/ });
  expect(navigate).not.toHaveBeenCalled();
  expect(screen.queryByText(messages.access_disabled)).toBeNull();
  replies.set("/api/v1/users/me/", user);
  fireEvent.click(retry);
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/spaces/personal/chat", { replace: true })
  );
});

it("blocks a previously admitted page when the organisation is suspended during its read", async () => {
  generation = "session-a";
  replies.set(
    "/api/v1/users/me/",
    Response.json({ message: "Suspended", eneo_error_code: 9025 }, { status: 403 })
  );
  await route("/deactivated");
  await waitFor(async () =>
    expect((await import("@/lib/api/refusal")).getSessionSnapshot()).toEqual({
      status: "stale",
      destination: "/deactivated"
    })
  );
  expect(screen.getByRole("link", { name: messages.logout }).getAttribute("href")).toBe("/logout");
  expect(callsTo("/api/v1/auth/session/logout/")).toHaveLength(0);
  expect(navigate).not.toHaveBeenCalled();
});

it.each(["/invite", "/invite/abc"])("renders the invitation notice at %s", async (path) => {
  await route(path);
  expect(await screen.findByRole("heading", { name: messages.invite_title })).toBeTruthy();
  expect(screen.getByRole("link", { name: messages.invite_go_to_login }).getAttribute("href")).toBe(
    "/login"
  );
});

it("keeps an anonymous password-change continuation on this installation", async () => {
  const router = await route("/password-change?next=https://evil.example");
  await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
  expect(router.state.location.search.next).toBe("/spaces/personal/chat");
  const target = new URL(navigate.mock.calls[0]![0], window.location.origin);
  expect(target.pathname).toBe("/login");
  expect(target.searchParams.get("next")).toBe("/password-change?next=%2Fspaces%2Fpersonal%2Fchat");
});

it("shows the local password fields and save action outside the authenticated shell", async () => {
  generation = "session-a";
  replies.set("/api/v1/users/me/", {
    id: "user-a",
    email: "test@example.test",
    password_status: { change_required: true, reason: "admin_set" },
    password_change: {
      source: "eneo",
      policy: {
        min_length: 12,
        max_bytes: 72,
        requires_uppercase: true,
        requires_lowercase: true,
        requires_number: true,
        requires_symbol: false
      }
    }
  });
  await route("/password-change?next=%2Fadmin");
  expect(
    await screen.findByLabelText(messages.current_password, { exact: true, selector: "input" })
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: messages.save })).toBeTruthy();
  expect(navigate).not.toHaveBeenCalled();
  await expectNoAxeViolations();
});

it("renders a module failure with the handoff's document metadata", async () => {
  await route("/module-login/failed?reason=x");
  expect(await screen.findByRole("heading", { name: messages.module_login_failed })).toBeTruthy();
  expect(screen.getByText(messages.module_login_invalid_request)).toBeTruthy();
  expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
    "noindex, nofollow, noarchive"
  );
  expect(document.querySelector('meta[name="referrer"]')?.getAttribute("content")).toBe(
    "no-referrer"
  );
});

it("recovers a failed password-capability read through an explicit retry", async () => {
  generation = "session-a";
  replies.set("/api/v1/users/me/", new Response(null, { status: 503 }));
  await route("/password-change");
  const retry = await screen.findByRole("button", { name: /Försök igen/ });
  expect(callsTo("/api/v1/users/me/")).toHaveLength(1);
  replies.set("/api/v1/users/me/", {
    id: "user-a",
    email: "test@example.test",
    password_status: { change_required: true, reason: "admin_set" },
    password_change: {
      source: "eneo",
      policy: {
        min_length: 12,
        max_bytes: 72,
        requires_uppercase: true,
        requires_lowercase: true,
        requires_number: true,
        requires_symbol: false
      }
    }
  });
  fireEvent.click(retry);
  expect(await screen.findByRole("button", { name: messages.save })).toBeTruthy();
  expect(callsTo("/api/v1/users/me/")).toHaveLength(2);
  expect(navigate).not.toHaveBeenCalled();
});

it("uses the real session transport for a module ticket and preserves its generation", async () => {
  generation = "session-a";
  const target = "https://module.example/callback?ticket=dummy";
  replies.set(
    "/api/v1/module-auth/tickets/",
    Response.json(
      { redirect_target: target },
      { status: 201, headers: { [GENERATION]: generation } }
    )
  );
  await route(
    "/module-login?module_key=module&redirect_uri=https%3A%2F%2Fmodule.example%2Fcallback&state=test-state"
  );
  await waitFor(() => expect(navigate).toHaveBeenCalledExactlyOnceWith(target, { replace: true }));
  const calls = callsTo("/api/v1/module-auth/tickets/");
  expect(calls).toHaveLength(1);
  expect((calls[0]![0] as Request).headers.get(GENERATION)).toBe("session-a");
});

it("keeps the refusal owner's destination when a module ticket discovers a changed session", async () => {
  generation = "session-a";
  replies.set(
    "/api/v1/module-auth/tickets/",
    Response.json({ message: "Changed", eneo_error_code: 9090 }, { status: 401 })
  );
  await route(
    "/module-login?module_key=module&redirect_uri=https%3A%2F%2Fmodule.example%2Fcallback&state=test-state"
  );
  expect(await screen.findByRole("heading", { name: messages.session_changed_title })).toBeTruthy();
  expect(navigate).not.toHaveBeenCalled();
});

it("routes the shared registered integration URI to the popup handoff", async () => {
  const postMessage = vi.fn();
  vi.stubGlobal("opener", { postMessage });
  vi.spyOn(window, "close").mockImplementation(() => {});
  const { INTEGRATION_CALLBACK_PATH, INTEGRATION_CALLBACK_MESSAGE_TYPE } =
    await import("@/features/integrations/callback-message");
  await route(INTEGRATION_CALLBACK_PATH + "?code=test-code&state=test-state");
  await waitFor(() => expect(postMessage).toHaveBeenCalledTimes(1));
  expect(postMessage).toHaveBeenCalledWith(
    {
      type: INTEGRATION_CALLBACK_MESSAGE_TYPE,
      code: "test-code",
      state: "test-state",
      params: "?code=test-code&state=test-state"
    },
    window.location.origin
  );
  expect(window.close).toHaveBeenCalledTimes(1);
});

it.each(["getItem", "setItem"] as const)(
  "keeps a single tenant as an explicit link when storage %s fails, including after failed authentication",
  async (operation) => {
    replies.set("/api/v1/auth/federation-status", { has_multi_tenant_federation: true });
    replies.set("/api/v1/auth/tenants", { tenants: [{ slug: "first", name: "First" }] });
    vi.spyOn(Storage.prototype, operation).mockImplementation(() => {
      throw new DOMException("Storage is blocked", "SecurityError");
    });
    for (const path of ["/login", "/login?message=oidc_callback_failed"]) {
      await route(path);
      expect((await screen.findByRole("link", { name: "First" })).getAttribute("href")).toBe(
        "/api/v1/auth/browser/initiate?tenant=first"
      );
      expect(navigate).not.toHaveBeenCalled();
      cleanup();
    }
  }
);

it.each(["single", "multi"])(
  "preserves credentials when discovery recovers into %s federation",
  async (mode) => {
    replies.set("/api/v1/auth/federation-status", new Response(null, { status: 503 }));
    await route("/login");
    expect(await screen.findByRole("button", { name: messages.login })).toBeTruthy();
    const email = screen.getByLabelText(/^E-post/);
    const password = screen.getByLabelText(/^Lösenord/);
    fireEvent.change(email, { target: { value: "person@example.com" } });
    fireEvent.change(password, { target: { value: "entered-value" } });
    const retry = await screen.findByRole("button", { name: /Försök igen/ });
    if (mode === "multi") multiTenant();
    else replies.set("/api/v1/auth/federation-status", { has_global_oidc_config: true });
    fireEvent.click(retry);
    expect(
      await screen.findByRole("link", {
        name: mode === "multi" ? "First" : messages.login_with_sso
      })
    ).toBeTruthy();
    expect(callsTo("/api/v1/auth/federation-status")).toHaveLength(2);
    expect((screen.getByLabelText(/^E-post/) as HTMLInputElement).value).toBe("person@example.com");
    expect((screen.getByLabelText(/^Lösenord/) as HTMLInputElement).value).toBe("entered-value");
    expect(navigate).not.toHaveBeenCalled();
  }
);

it("keeps explicit callback recovery available when the tenant catalog is unavailable", async () => {
  multiTenant();
  replies.set("/api/v1/auth/tenants", new Response(null, { status: 503 }));
  await route("/login?tenant=first&message=oidc_callback_failed&next=%2Fadmin");
  expect(
    (await screen.findByRole("link", { name: messages.oidc_retry_login })).getAttribute("href")
  ).toBe("/api/v1/auth/browser/initiate?tenant=first&next=%2Fadmin");
  expect(callsTo("/api/v1/auth/tenants")).toHaveLength(0);
  const choose = screen.getByRole("button", { name: messages.oidc_choose_another_org });
  choose.focus();
  fireEvent.click(choose);
  expect(await screen.findByText(messages.failed_to_load_organizations)).toBeTruthy();
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByText(messages.select_your_organization))
  );
  multiTenant();
  fireEvent.click(screen.getByRole("button", { name: /Försök igen/ }));
  expect(await screen.findByRole("link", { name: "Second" })).toBeTruthy();
  expect(navigate).not.toHaveBeenCalled();
});

it.each([
  [
    "/logout?reason=password_changed&next=%2Fadmin",
    "/login?message=password_changed&next=%2Fadmin"
  ],
  ["/login/switch-organisation", "/login"]
])("commits %s once under StrictMode", async (path, destination) => {
  generation = "session-a";
  await route(path);
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith(destination, { replace: true })
  );
  expect(callsTo("/api/v1/auth/session/logout/")).toHaveLength(1);
  expect(document.querySelector("form")).toBeNull();
  expect(callsTo("/api/v1/auth/browser/initiate")).toHaveLength(0);
});
