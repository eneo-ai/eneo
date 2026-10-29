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
let replies: Map<string, unknown>;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  sessionStorage.clear();
  generation = null;
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
      return generation
        ? new Response(null, { status: 204, headers: { [GENERATION]: generation } })
        : new Response(null, { status: 401 });
    }
    if (!replies.has(path)) throw new Error(`Unexpected request: ${path}`);
    const reply = await replies.get(path);
    if (reply instanceof Response) return reply.clone();
    return Response.json(reply, {
      headers: path === "/api/v1/users/me/" && generation ? { [GENERATION]: generation } : {}
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
  const router = await route("/login?next=%2Fadmin");
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
  expect(fetcher).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
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

it("keeps password login available and recovers SSO discovery through an explicit retry", async () => {
  replies.set("/api/v1/auth/federation-status", new Response(null, { status: 503 }));
  await route("/login");
  expect(await screen.findByRole("button", { name: messages.login })).toBeTruthy();
  const retry = await screen.findByRole("button", { name: /Försök igen/ });
  replies.set("/api/v1/auth/federation-status", { has_global_oidc_config: true });
  fireEvent.click(retry);
  expect(await screen.findByRole("link", { name: messages.login_with_sso })).toBeTruthy();
  expect(callsTo("/api/v1/auth/federation-status")).toHaveLength(2);
  expect(screen.getByRole("button", { name: messages.login })).toBeTruthy();
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
