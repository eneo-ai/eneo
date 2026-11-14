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

  // What an administrator sees by what they hold beside admin. The windows are
  // admin settings and stay in every row.
  it("lets someone who may place holds read the rules, with only the windows to save", async () => {
    page(["admin", "retention_holds"]);
    expect(await screen.findByText(/Du kan läsa gallringen/)).toBeTruthy();
    const radio = await screen.findByRole("radio", { name: /^Gallringstid för organisationen/ });
    expect((radio as HTMLInputElement).disabled).toBe(true);
    await screen.findByRole("spinbutton", { name: /Felsökningsunderlag, dagar/ });
    expect(screen.getAllByRole("button", { name: "Spara inställningar" })).toHaveLength(1);
  });

  it("tells an administrator without a retention permission what is missing, and asks nothing the backend refuses", async () => {
    const { container } = page(["admin"]);
    expect(
      await screen.findByText("Du har inte behörighet att se gallringsreglerna.")
    ).toBeTruthy();
    expect(screen.getByText(/Gallring – hantera regler/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Gå till Roller" }).getAttribute("href")).toBe(
      "/admin/roles"
    );
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("combobox", { name: /Yta/ })).toBeNull();
    // The windows still load and save.
    await screen.findByRole("spinbutton", { name: /Felsökningsunderlag, dagar/ });
    expect(screen.getAllByRole("button", { name: "Spara inställningar" })).toHaveLength(1);
    expect(backend.GET.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/settings/flow-retention-policy"
    ]);
    await expectNoAxeViolations(container);
  });

  it("makes the link to Roles 44 px tall on touch", async () => {
    page(["admin"]);
    // jsdom applies no CSS: the coarse-pointer height is asserted as its class.
    const link = await screen.findByRole("link", { name: "Gå till Roller" });
    expect(link.className).toContain("pointer-coarse:min-h-11");
  });

  it("lets someone who manages retention change the rules", async () => {
    page(["admin", "retention_manage"]);
    const radio = await screen.findByRole("radio", { name: /^Gallringstid för organisationen/ });
    expect((radio as HTMLInputElement).disabled).toBe(false);
    expect(screen.queryByText(/Du kan läsa gallringen/)).toBeNull();
    await screen.findByRole("spinbutton", { name: /Felsökningsunderlag, dagar/ });
    expect(screen.getAllByRole("button", { name: "Spara inställningar" })).toHaveLength(2);
  });
});
