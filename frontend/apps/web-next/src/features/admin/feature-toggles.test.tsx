// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({ PATCH: vi.fn() }));
const refresh = vi.hoisted(() => vi.fn());
const toastApiError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/api/toast", () => ({ toastApiError }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { FeatureToggles } from "./feature-toggles";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderToggles() {
  renderInApp(<FeatureToggles />, {
    appContext: testAppContext({
      settings: {
        using_templates: true,
        audit_logging_enabled: false,
        provisioning: false,
        whats_new_enabled: true
      }
    })
  });
}

const saved = () => Promise.resolve({ data: { enabled: true }, response: new Response("{}") });

it("renders labelled, described switches in a titled card", async () => {
  renderToggles();
  expect(screen.getByRole("region", { name: "Funktioner" })).toBeTruthy();
  const templates = screen.getByRole("switch", { name: "Aktivera mallar" });
  expect((templates as HTMLInputElement).checked).toBe(true);
  expect(templates.getAttribute("aria-describedby")).toBeTruthy();
  const described = document.getElementById(templates.getAttribute("aria-describedby")!);
  expect(described?.textContent).toBe(messages.enable_templates_description);
  expect(screen.getAllByRole("switch")).toHaveLength(4);
  await expectNoAxeViolations(document.body);
});

it("saves a toggle and refreshes the server layout", async () => {
  api.PATCH.mockResolvedValue({ data: { enabled: true }, response: new Response("{}") });
  renderToggles();
  const audit = screen.getByRole("switch", { name: "Aktivera granskningsloggning" });

  fireEvent.click(audit);

  await waitFor(() => expect((audit as HTMLInputElement).checked).toBe(true));
  expect(api.PATCH).toHaveBeenCalledWith("/api/v1/settings/audit-logging", {
    body: { enabled: true }
  });
  await waitFor(() => expect(refresh).toHaveBeenCalled());
  // The switch keeps focus while saving: it is never disabled.
  expect((audit as HTMLInputElement).disabled).toBe(false);
});

it("reverts and reports the error when saving fails", async () => {
  api.PATCH.mockResolvedValue({
    error: { message: "nope" },
    response: new Response("{}", { status: 500 })
  });
  renderToggles();
  const provisioning = screen.getByRole("switch", { name: "Automatisk kontoskapning (SSO)" });

  fireEvent.click(provisioning);

  await waitFor(() => expect(toastApiError).toHaveBeenCalled());
  expect((provisioning as HTMLInputElement).checked).toBe(false);
  expect(refresh).not.toHaveBeenCalled();
});

it("saves a press made during a save once that save is done", async () => {
  const saves: Array<() => void> = [];
  api.PATCH.mockImplementation(() => new Promise((resolve) => saves.push(() => resolve(saved()))));
  renderToggles();
  const audit = screen.getByRole("switch", { name: "Aktivera granskningsloggning" });

  fireEvent.click(audit);
  await waitFor(() => expect((audit as HTMLInputElement).checked).toBe(true));
  // Pressed again while the first save runs: shown at once, not dropped.
  fireEvent.click(audit);
  await waitFor(() => expect((audit as HTMLInputElement).checked).toBe(false));
  expect(api.PATCH).toHaveBeenCalledTimes(1);

  await act(async () => saves[0]!());
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/settings/audit-logging", {
    body: { enabled: false }
  });
  await act(async () => saves[1]!());
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
  expect((audit as HTMLInputElement).checked).toBe(false);
});
