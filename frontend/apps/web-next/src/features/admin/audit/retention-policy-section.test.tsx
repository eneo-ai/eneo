// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const announce = vi.hoisted(() => vi.fn());
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => announce
}));

import { RetentionPolicySection } from "./retention-policy-section";

const policy = {
  retention_days: 90,
  last_purge_at: "2026-09-25T02:00:00Z",
  purge_count: 12
};
const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

beforeEach(() => {
  api.GET.mockImplementation(() => ok(policy));
  api.PUT.mockImplementation((_path: string, init: { body: { retention_days: number } }) =>
    ok({ ...policy, retention_days: init.body.retention_days })
  );
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RetentionPolicySection", () => {
  it("shows the period as text and saves a changed value, then returns focus to Ändra", async () => {
    const { container } = renderInApp(<RetentionPolicySection />);
    expect(screen.getByRole("heading", { level: 2, name: "Gallringspolicy" })).toBeTruthy();
    expect(await screen.findByText("90 dagar")).toBeTruthy();
    expect(screen.getByText(/Senaste rensning tog bort 12 poster/)).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: "Ändra" }));
    const field = screen.getByRole("textbox", { name: "Gallringsperiod" });
    expect((field as HTMLInputElement).value).toBe("90");
    fireEvent.change(field, { target: { value: "180" } });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.PUT).toHaveBeenCalledWith("/api/v1/audit/retention-policy", {
        body: { retention_days: 180 }
      })
    );
    expect(await screen.findByText("180 dagar")).toBeTruthy();
    expect(announce).toHaveBeenCalledWith("Gallringsperioden är sparad.");
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Ändra" }))
    );
  });

  it("reports a value outside 1–2555 at the field and sends nothing", async () => {
    renderInApp(<RetentionPolicySection />);
    fireEvent.click(await screen.findByRole("button", { name: "Ändra" }));
    const field = screen.getByRole("textbox", { name: "Gallringsperiod" });
    fireEvent.change(field, { target: { value: "3000" } });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));

    expect(screen.getByText("Ange ett heltal mellan 1 och 2555 dagar.")).toBeTruthy();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field);
    expect(api.PUT).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("90 dagar")).toBeTruthy();
  });

  it("shows the shared error state with a retry when the policy cannot be loaded", async () => {
    api.GET.mockImplementationOnce(() =>
      Promise.reject(new EneoApiError("boom", { status: 503, code: 9024 }))
    );
    renderInApp(<RetentionPolicySection />);
    expect(await screen.findByText("Innehållet kunde inte hämtas")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("90 dagar")).toBeTruthy();
  });
});
