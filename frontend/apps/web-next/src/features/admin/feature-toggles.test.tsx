// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";

const api = vi.hoisted(() => ({ PATCH: vi.fn() }));
const refresh = vi.hoisted(() => vi.fn());
const toastApiError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/api/toast", () => ({ toastApiError }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({
    settings: {
      using_templates: true,
      audit_logging_enabled: false,
      provisioning: false,
      whats_new_enabled: true
    }
  })
}));

import { FeatureToggles } from "./feature-toggles";

beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderToggles() {
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <FeatureToggles />
    </NextIntlClientProvider>
  );
}

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

  expect((audit as HTMLInputElement).checked).toBe(true);
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
