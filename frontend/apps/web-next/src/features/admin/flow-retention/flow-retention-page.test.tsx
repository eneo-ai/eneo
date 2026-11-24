// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { FlowRetentionPage } from "./flow-retention-page";

const backend = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: backend }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const windows = { run_debug_evidence_days: 30, flow_runtime_upload_abandonment_days: null };
const answered = (data: unknown) => ({ data, response: new Response("{}") });

beforeEach(() => {
  backend.GET.mockImplementation(async () => answered(windows));
  backend.PATCH.mockImplementation(async () => answered(windows));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const page = (permissions: Permission[]) =>
  renderInApp(<FlowRetentionPage />, { appContext: testAppContext({ permissions }) });

describe("FlowRetentionPage", () => {
  it("saves the upload and debug windows", async () => {
    const { container } = page(["admin"]);
    await screen.findByRole("spinbutton", { name: /Felsökningsunderlag, dagar/ });
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PATCH).toHaveBeenCalledTimes(1));
    expect(backend.PATCH.mock.calls[0]![1].body).toEqual({
      flow_runtime_upload_abandonment_days: null,
      run_debug_evidence_days: 30
    });
    await expectNoAxeViolations(container);
  });

  // Run history follows each space's time, so the page reads no Flow policy and has
  // no organisation or space period, whatever retention permission the viewer holds.
  it.each<Permission[]>([["admin"], ["admin", "retention_manage"]])(
    "reads only the windows for %j",
    async (...permissions) => {
      page(permissions);
      await screen.findByRole("spinbutton", { name: /Felsökningsunderlag, dagar/ });
      expect(screen.queryByRole("radio")).toBeNull();
      expect(screen.queryByRole("combobox")).toBeNull();
      expect(backend.GET.mock.calls.map(([path]) => path)).toEqual([
        "/api/v1/settings/flow-retention-policy"
      ]);
    }
  );
});
