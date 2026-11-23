// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { makeFlow, makeStep } from "./flow-fixtures";
import { FlowSettings, SettingsSummary } from "./flow-settings";

const backend = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: backend }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const configured = {
  state: "configured",
  source: "space",
  effective_days: 60,
  contributors: { space: { days: 60 }, flow: null }
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

async function openDialog() {
  renderSettings(["retention_manage"]);
  fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
  return screen.findByRole("spinbutton", { name: /Egen tid för det här flödet/ });
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
    expect(screen.queryByText(/sparat på flödet/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Ändra gallring" })).toBeNull();
  });

  it("shows a longer saved flow time beside the space's shorter one that applies", () => {
    renderInApp(
      <SettingsSummary
        flow={makeFlow({
          run_history_retention: {
            ...configured,
            contributors: { space: { days: 60 }, flow: { days: 90 } }
          }
        })}
        transcription={resources}
      />
    );
    expect(screen.getByText(/60 dagar, ärvt från ytan/)).toBeTruthy();
    expect(screen.getByText("90 dagar sparat på flödet. Ytans kortare tid gäller.")).toBeTruthy();
  });

  it("offers the change only to someone who manages retention", () => {
    renderSettings(["flows"]);
    expect(screen.queryByRole("button", { name: "Ändra gallring" })).toBeNull();
    cleanup();
    renderSettings(["retention_manage"]);
    expect(screen.getByRole("button", { name: "Ändra gallring" })).toBeTruthy();
  });

  it("shows the space's time while the field is empty, and saves a flow time", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const days = await openDialog();
    expect(screen.getByText(/Från ytan: 60 dagar/)).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({ policy: { days: 30 } });
  });

  it("says the space has no time when nothing applies", async () => {
    backend.GET.mockResolvedValue(settings(null, null));
    await openDialog();
    expect(screen.getByText(/Ytan har ingen tid/)).toBeTruthy();
  });

  it("names the space's cap next to the field when the backend refuses a longer time", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockRejectedValue(
      new EneoApiError("The retention period is longer than the limit that applies here.", {
        status: 400,
        code: 9086,
        reason: "retention_exceeds_space",
        context: { cap_days: 7, cap_origin: "space" }
      })
    );
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "90" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    expect(await screen.findByText("Ytan tillåter högst 7 dagar.")).toBeTruthy();
    // A new value clears the refusal.
    fireEvent.change(days, { target: { value: "5" } });
    fireEvent.blur(days);
    expect(screen.queryByText("Ytan tillåter högst 7 dagar.")).toBeNull();
  });

  it("empties the flow's own time to use the space's again", async () => {
    backend.GET.mockResolvedValue(settings({ days: 90 }, { days: 60 }));
    backend.PUT.mockResolvedValue(settings(null, { days: 60 }));
    const days = await openDialog();
    expect(screen.getByText("90 dagar sparat på flödet. Ytans kortare tid gäller.")).toBeTruthy();
    fireEvent.change(days, { target: { value: "" } });
    fireEvent.blur(days);
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
