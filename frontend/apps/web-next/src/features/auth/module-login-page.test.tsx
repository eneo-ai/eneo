// @vitest-environment jsdom
import { StrictMode } from "react";
import { waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { navigateTo } from "@/lib/navigate-to";
import { ModuleLoginPage } from "./module-login-page";

vi.mock("@/lib/api/browser", () => ({ browserApi: { POST: vi.fn() } }));
vi.mock("@/lib/navigate-to", () => ({ navigateTo: vi.fn() }));
vi.mock("@/lib/api/refusal", () => ({
  getSessionSnapshot: () => ({ status: "bound", generation: "session-a" })
}));
const search =
  "?module_key=module&redirect_uri=https%3A%2F%2Fmodule.example%2Fcallback&state=test-state";

beforeEach(() => vi.clearAllMocks());
const mount = (query = search) =>
  renderInApp(
    <StrictMode>
      <ModuleLoginPage search={query} accessibilityStatementUrl={null} />
    </StrictMode>
  );

it("issues one ticket under StrictMode and replaces the document with the exact returned target", async () => {
  const target = "https://module.example/callback?ticket=dummy&state=test-state";
  vi.mocked(browserApi.POST).mockResolvedValue({
    data: { redirect_target: target },
    response: new Response(null, { status: 201 })
  });
  mount();
  await waitFor(() =>
    expect(navigateTo).toHaveBeenCalledExactlyOnceWith(target, { replace: true })
  );
  expect(browserApi.POST).toHaveBeenCalledExactlyOnceWith("/api/v1/module-auth/tickets/", {
    body: {
      module_key: "module",
      redirect_uri: "https://module.example/callback",
      state: "test-state"
    },
    cache: "no-store",
    redirect: "error"
  });
});

it.each([
  [401, "/login?" + new URLSearchParams({ next: "/module-login" + search })],
  [422, "/module-login/failed?reason=invalid_request"],
  [403, "/module-login/failed?reason=module_unavailable"],
  [500, "/module-login/failed?reason=service_unavailable"]
])("handles a %s response without retrying", async (status, destination) => {
  vi.mocked(browserApi.POST).mockResolvedValue({
    error: {},
    response: new Response(null, { status: Number(status) })
  });
  mount();
  await waitFor(() =>
    expect(navigateTo).toHaveBeenCalledExactlyOnceWith(destination, { replace: true })
  );
  expect(browserApi.POST).toHaveBeenCalledTimes(1);
});

it.each([{}, { redirect_target: "javascript:alert(1)" }, new TypeError("Offline")])(
  "refuses an unusable ticket result %j",
  async (result) => {
    if (result instanceof Error) vi.mocked(browserApi.POST).mockRejectedValue(result);
    else
      vi.mocked(browserApi.POST).mockResolvedValue({
        data: result,
        response: new Response(null, { status: 201 })
      });
    mount();
    await waitFor(() =>
      expect(navigateTo).toHaveBeenCalledExactlyOnceWith(
        "/module-login/failed?reason=service_unavailable",
        { replace: true }
      )
    );
    expect(browserApi.POST).toHaveBeenCalledTimes(1);
  }
);

it("resumes an anonymous document when the session transport refuses before sending", async () => {
  vi.mocked(browserApi.POST).mockRejectedValue(
    new EneoApiError("No browser session", { status: 401 })
  );
  mount();
  await waitFor(() =>
    expect(navigateTo).toHaveBeenCalledExactlyOnceWith(
      "/login?" + new URLSearchParams({ next: "/module-login" + search }),
      { replace: true }
    )
  );
});

it.each(["module_key", "redirect_uri", "state"])(
  "does not issue a ticket with a missing or duplicate %s",
  async (key) => {
    for (const duplicate of [false, true]) {
      vi.clearAllMocks();
      const params = new URLSearchParams(search);
      if (duplicate) params.append(key, "extra");
      else params.delete(key);
      const view = mount("?" + params.toString());
      await waitFor(() =>
        expect(navigateTo).toHaveBeenCalledExactlyOnceWith(
          "/module-login/failed?reason=invalid_request",
          { replace: true }
        )
      );
      expect(browserApi.POST).not.toHaveBeenCalled();
      view.unmount();
    }
  }
);
