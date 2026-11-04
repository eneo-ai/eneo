// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { makeFlow, makeStep } from "./flow-fixtures";
import { FlowSettings, SettingsSummary } from "./flow-settings";

const backend = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: backend }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const contributors = { organization: null, space: null, flow: null };
const configured = {
  state: "configured",
  source: "space",
  mode: "review_required",
  effective_days: 60,
  contributors
} as const;
const answered = (data: unknown) => ({ data, response: new Response("{}") });
const settings = (local: unknown, inherited: unknown) =>
  answered({
    scope: "flow",
    scope_id: "flow-1",
    local_policy: local,
    inherited_policy: inherited,
    effective: configured
  });
const resources = { models: [], services: [] };

afterEach(() => {
  cleanup();
  backend.GET.mockReset();
  backend.PUT.mockReset();
});

function renderSettings(permissions: Permission[]) {
  return renderInApp(
    <FlowSettings
      flow={makeFlow({ run_history_retention: configured })}
      canEdit
      transcription={resources}
      onSave={vi.fn()}
    />,
    { appContext: testAppContext({ permissions }) }
  );
}

describe("flow retention", () => {
  it("says what applies, and where it comes from, to anyone reading the flow", () => {
    renderInApp(
      <SettingsSummary
        flow={makeFlow({ run_history_retention: configured })}
        transcription={resources}
      />
    );
    expect(screen.getByText(/60 dagar, ärvt från ytan/)).toBeTruthy();
    expect(screen.getByText("Granskas före rensning")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ändra gallring" })).toBeNull();
  });

  it("offers the change only to someone who manages retention", () => {
    renderSettings(["flows"]);
    expect(screen.queryByRole("button", { name: "Ändra gallring" })).toBeNull();
    cleanup();
    renderSettings(["retention_manage"]);
    expect(screen.getByRole("button", { name: "Ändra gallring" })).toBeTruthy();
  });

  it("saves a period of the flow's own, and asks for the days when nothing gives them", async () => {
    backend.GET.mockResolvedValue(settings(null, null));
    backend.PUT.mockResolvedValue(
      answered({
        scope: "flow",
        scope_id: "flow-1",
        local_policy: { days: 90, mode: "preserve" },
        inherited_policy: null,
        effective: { ...configured, source: "flow", effective_days: 90, mode: "preserve" }
      })
    );
    const { container } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    fireEvent.click(await screen.findByRole("radio", { name: /Egen tid/ }));
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    expect(await screen.findByText("Ange ett heltal från 1 till 2555.")).toBeTruthy();
    expect(backend.PUT).not.toHaveBeenCalled();

    const days = screen.getByRole("spinbutton", { name: /Dagar/ });
    fireEvent.change(days, { target: { value: "90" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body.policy.days).toBe(90);
  });

  it("clears the flow's own period to inherit again", async () => {
    backend.GET.mockResolvedValue(
      settings({ days: 90, mode: "preserve" }, { days: 60, mode: "review_required" })
    );
    backend.PUT.mockResolvedValue(settings(null, { days: 60, mode: "review_required" }));
    renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    fireEvent.click(await screen.findByRole("radio", { name: /Ärv/ }));
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({ policy: null });
  });
});

describe("the flow's security classification", () => {
  const steps = [
    makeStep(1, { output_classification_override: 3 }),
    // The same level as the space's raises nothing.
    makeStep(2, { output_classification_override: 2 })
  ];

  it("names the space's, and says how many steps raise it", () => {
    renderInApp(
      <SettingsSummary
        flow={makeFlow({ steps })}
        transcription={resources}
        classification={{ name: "Intern", security_level: 2 }}
      />
    );
    expect(screen.getByText(/Intern, 1 steg höjer nivån/)).toBeTruthy();
  });

  it("stays out of a tenant without classifications", () => {
    renderInApp(<SettingsSummary flow={makeFlow()} transcription={resources} />);
    expect(screen.queryByText("Säkerhetsklass")).toBeNull();
  });
});
