// @vitest-environment jsdom
import { StrictMode } from "react";
import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { navigateTo } from "@/lib/navigate-to";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import { SHAREPOINT_OAUTH_STATE_KEY } from "@/features/admin/integrations/integrations";
import { INTEGRATION_CALLBACK_MESSAGE_TYPE } from "./callback-message";
import { CallbackHandoff } from "./callback-handoff";

vi.mock("@/lib/api/browser", () => ({ browserApi: { POST: vi.fn() } }));
vi.mock("@/lib/navigate-to", () => ({ navigateTo: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubGlobal("opener", null);
  vi.spyOn(window, "close").mockImplementation(() => {});
  window.history.replaceState(
    {},
    "",
    "/integrations/callback/token/?code=test-code&state=test-state"
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const mount = () =>
  renderInApp(
    <StrictMode>
      <CallbackHandoff />
    </StrictMode>
  );

it("posts once to the opener's same origin without consuming unrelated service-account state", async () => {
  const postMessage = vi.fn();
  vi.stubGlobal("opener", { postMessage });
  sessionStorage.setItem(SHAREPOINT_OAUTH_STATE_KEY, JSON.stringify({ state: "test-state" }));
  mount();
  await waitFor(() =>
    expect(postMessage).toHaveBeenCalledExactlyOnceWith(
      {
        type: INTEGRATION_CALLBACK_MESSAGE_TYPE,
        code: "test-code",
        state: "test-state",
        params: "?code=test-code&state=test-state"
      },
      window.location.origin
    )
  );
  expect(window.close).toHaveBeenCalledTimes(1);
  expect(browserApi.POST).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(SHAREPOINT_OAUTH_STATE_KEY)).not.toBeNull();
});

it("consumes matching state and submits the full-page callback once under StrictMode", async () => {
  sessionStorage.setItem(SHAREPOINT_OAUTH_STATE_KEY, JSON.stringify({ state: "test-state" }));
  vi.mocked(browserApi.POST).mockResolvedValue({
    data: {},
    response: new Response(null, { status: 200 })
  });
  mount();
  await waitFor(() =>
    expect(navigateTo).toHaveBeenCalledExactlyOnceWith("/admin/integrations", { replace: true })
  );
  expect(browserApi.POST).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/admin/sharepoint/service-account/auth/callback",
    { body: { auth_code: "test-code", state: "test-state" } }
  );
  expect(sessionStorage.getItem(SHAREPOINT_OAUTH_STATE_KEY)).toBeNull();
  expect(window.close).not.toHaveBeenCalled();
});

it.each([null, "broken", '{"state":"different"}'])(
  "rejects absent or mismatched full-page state %s",
  async (stored) => {
    if (stored) sessionStorage.setItem(SHAREPOINT_OAUTH_STATE_KEY, stored);
    mount();
    expect(await screen.findByRole("heading", { name: "Autentisering misslyckades" })).toBeTruthy();
    expect(browserApi.POST).not.toHaveBeenCalled();
    expect(navigateTo).not.toHaveBeenCalled();
    await expectNoAxeViolations();
  }
);

it("renders an OAuth failure as text without forwarding or submitting a code", async () => {
  const postMessage = vi.fn();
  vi.stubGlobal("opener", { postMessage });
  window.history.replaceState(
    {},
    "",
    "/integrations/callback/token?error=denied&error_description=%3Cscript%3Ebad%3C%2Fscript%3E"
  );
  mount();
  expect(await screen.findByText("<script>bad</script>")).toBeTruthy();
  expect(document.querySelector("main script")).toBeNull();
  expect(postMessage).not.toHaveBeenCalled();
  expect(browserApi.POST).not.toHaveBeenCalled();
});

it("shows a recoverable failure when browser storage is unavailable", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new DOMException("Blocked", "SecurityError");
  });
  mount();
  expect(await screen.findByRole("heading", { name: "Autentisering misslyckades" })).toBeTruthy();
  expect(browserApi.POST).not.toHaveBeenCalled();
});
