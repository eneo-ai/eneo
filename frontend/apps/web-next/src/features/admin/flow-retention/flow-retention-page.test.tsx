// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { FlowRetentionPage } from "./flow-retention-page";

const backend = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: backend }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const off = {
  state: "off",
  source: "none",
  contributors: { organization: null, space: null, flow: null }
};
const answered = (data: unknown) => ({ data, response: new Response("{}") });
const policy = (scope: string, local: unknown, inherited: unknown = null) => ({
  scope,
  scope_id: `${scope}-1`,
  local_policy: local,
  inherited_policy: inherited,
  effective: off
});

beforeEach(() => {
  backend.GET.mockImplementation(async (path: string) => {
    if (path.endsWith("/targets/spaces")) {
      return answered({ items: [{ id: "space-1", name: "Socialtjänsten" }], has_more: false });
    }
    if (path.endsWith("/spaces/{space_id}")) {
      return answered(policy("space", null, { days: 60, mode: "preserve" }));
    }
    if (path.endsWith("/flow-retention-policy")) {
      return answered({
        run_debug_evidence_days: 30,
        flow_runtime_upload_abandonment_days: null
      });
    }
    return answered(policy("organization", { days: 60, mode: "preserve" }));
  });
  backend.PUT.mockImplementation(async () => answered(policy("organization", null)));
  backend.PATCH.mockImplementation(async () =>
    answered({ run_debug_evidence_days: 30, flow_runtime_upload_abandonment_days: null })
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const page = (permissions: Permission[]) =>
  renderInApp(<FlowRetentionPage />, { appContext: testAppContext({ permissions }) });

describe("FlowRetentionPage", () => {
  it("shows the organisation's period and clears it", async () => {
    const { container } = page(["admin", "retention_manage"]);
    fireEvent.click(await screen.findByRole("radio", { name: /^Ingen gallringstid/ }));
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getAllByRole("button", { name: "Spara inställningar" })[0]!);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({ policy: null });
  });

  it("gives a space its own period through the space's endpoint", async () => {
    page(["admin", "retention_manage"]);
    fireEvent.click(await screen.findByRole("combobox", { name: /Yta/ }));
    fireEvent.click(await screen.findByRole("option", { name: "Socialtjänsten" }));
    expect(await screen.findByText("60 dagar från organisationen.")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Egen tid för den här ytan/ }));
    const save = screen.getAllByRole("button", { name: "Spara inställningar" });
    fireEvent.click(save[1]!);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    const [path, options] = backend.PUT.mock.calls[0]!;
    expect(path).toContain("/spaces/{space_id}");
    expect(options.params.path.space_id).toBe("space-1");
    expect(options.body.policy.days).toBe(60);
  });

  it("saves the upload and debug windows", async () => {
    page(["admin", "retention_manage"]);
    await screen.findByRole("spinbutton", { name: /Felsökningsunderlag, dagar/ });
    const buttons = await screen.findAllByRole("button", { name: "Spara inställningar" });
    fireEvent.click(buttons.at(-1)!);
    await waitFor(() => expect(backend.PATCH).toHaveBeenCalledTimes(1));
    expect(backend.PATCH.mock.calls[0]![1].body).toEqual({
      flow_runtime_upload_abandonment_days: null,
      run_debug_evidence_days: 30
    });
  });

  it("lets someone who may not manage retention read it, with nothing to save there", async () => {
    page(["admin"]);
    expect(await screen.findByText(/Du kan läsa gallringen/)).toBeTruthy();
    const radio = await screen.findByRole("radio", { name: /^Gallringstid för organisationen/ });
    expect((radio as HTMLInputElement).disabled).toBe(true);
    // Only the windows, which an administrator may set, can be saved.
    await screen.findByRole("spinbutton", { name: /Felsökningsunderlag, dagar/ });
    expect(screen.getAllByRole("button", { name: "Spara inställningar" })).toHaveLength(1);
  });
});
