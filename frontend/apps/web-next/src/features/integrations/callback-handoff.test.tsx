// @vitest-environment jsdom
import { StrictMode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { navigateTo } from "@/lib/navigate-to";
import { AppIntlProvider } from "@/components/providers/intl-provider";
import { AstryxProvider } from "@/components/providers/astryx-provider";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { SHAREPOINT_OAUTH_STATE_KEY } from "@/features/admin/integrations/integrations";
import { INTEGRATION_CALLBACK_MESSAGE_TYPE } from "./callback-message";
import { CallbackHandoff } from "./callback-handoff";

vi.mock("@/lib/api/browser", () => ({ browserApi: { POST: vi.fn() } }));
vi.mock("@/lib/navigate-to", () => ({ navigateTo: vi.fn() }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
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
  render(
    <StrictMode>
      <AppIntlProvider locale="sv" messages={messages}>
        <AstryxProvider>
          <CallbackHandoff />
        </AstryxProvider>
      </AppIntlProvider>
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
  expect(window.location.search).toBe("?code=test-code&state=test-state");
  expect(window.close).toHaveBeenCalledTimes(1);
  expect(browserApi.POST).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(SHAREPOINT_OAUTH_STATE_KEY)).not.toBeNull();
});

it("consumes matching state and submits the full-page callback once under StrictMode", async () => {
  sessionStorage.setItem(SHAREPOINT_OAUTH_STATE_KEY, JSON.stringify({ state: "test-state" }));
  window.history.replaceState({ returnMarker: "kept" }, "", window.location.href + "#result");
  const historyLength = window.history.length;
  vi.mocked(browserApi.POST).mockResolvedValue({
    data: { service_account_email: "service@example.se" },
    response: new Response(null, { status: 200 })
  });
  mount();
  expect(await screen.findByRole("heading", { name: "Tjänstekonto konfigurerat!" })).toBeTruthy();
  expect(screen.getByText("service@example.se")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Tillbaka till integrationer" }).getAttribute("href")
  ).toBe("/admin/integrations");
  expect(navigateTo).not.toHaveBeenCalled();
  expect(browserApi.POST).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/admin/sharepoint/service-account/auth/callback",
    { body: { auth_code: "test-code", state: "test-state" } }
  );
  expect(sessionStorage.getItem(SHAREPOINT_OAUTH_STATE_KEY)).toBeNull();
  expect(window.location.pathname + window.location.search + window.location.hash).toBe(
    "/integrations/callback/token/#result"
  );
  expect(window.history.state).toEqual({ returnMarker: "kept" });
  expect(window.history.length).toBe(historyLength);
  expect(window.close).not.toHaveBeenCalled();
});

it.each([null, "broken", '{"state":"different"}'])(
  "rejects absent or mismatched full-page state %s",
  async (stored) => {
    if (stored) sessionStorage.setItem(SHAREPOINT_OAUTH_STATE_KEY, stored);
    mount();
    expect(await screen.findByRole("heading", { name: "Autentisering misslyckades" })).toBeTruthy();
    expect(window.location.search).toBe("");
    expect(browserApi.POST).not.toHaveBeenCalled();
    expect(navigateTo).not.toHaveBeenCalled();
    expect(screen.getByText(/Inloggningen kunde inte kopplas/, { selector: "p" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Tillbaka till integrationer" })).toBeTruthy();
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
  expect(window.location.search).toBe("");
});

it("shows full-page provider refusal without submitting an accompanying code or consuming state", async () => {
  sessionStorage.setItem(SHAREPOINT_OAUTH_STATE_KEY, JSON.stringify({ state: "test-state" }));
  window.history.replaceState(
    {},
    "",
    "/integrations/callback/token?error=access_denied&error_description=%3Cscript%3Erefused%3C%2Fscript%3E&code=ignored&state=test-state"
  );
  mount();
  expect(await screen.findByText("<script>refused</script>", { selector: "p" })).toBeTruthy();
  expect(window.location.search).toBe("");
  expect(document.querySelector("main script")).toBeNull();
  expect(browserApi.POST).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(SHAREPOINT_OAUTH_STATE_KEY)).not.toBeNull();
  expect(screen.getByRole("link", { name: "Tillbaka till integrationer" })).toBeTruthy();
});

it("shows the mapped callback failure and a local return action after the one code submission", async () => {
  sessionStorage.setItem(SHAREPOINT_OAUTH_STATE_KEY, JSON.stringify({ state: "test-state" }));
  vi.mocked(browserApi.POST).mockResolvedValue({
    error: {
      message: "SharePoint credentials invalid",
      eneo_error_code: 9007,
      code: "sharepoint_credentials_invalid"
    },
    response: new Response("{}", { status: 400 })
  });
  mount();
  expect(
    await screen.findByText(/Microsoft nekade organisationens inloggning/, { selector: "p" })
  ).toBeTruthy();
  expect(window.location.search).toBe("");
  expect(browserApi.POST).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem(SHAREPOINT_OAUTH_STATE_KEY)).toBeNull();
  expect(
    screen.getByRole("link", { name: "Tillbaka till integrationer" }).getAttribute("href")
  ).toBe("/admin/integrations");
});

it("keeps matching state unconsumed when Microsoft returns no code", async () => {
  sessionStorage.setItem(SHAREPOINT_OAUTH_STATE_KEY, JSON.stringify({ state: "test-state" }));
  window.history.replaceState({}, "", "/integrations/callback/token/?state=test-state");
  mount();
  expect(
    await screen.findByText(/Microsoft skickade ingen inloggningskod/, { selector: "p" })
  ).toBeTruthy();
  expect(window.location.search).toBe("");
  expect(browserApi.POST).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(SHAREPOINT_OAUTH_STATE_KEY)).not.toBeNull();
});
