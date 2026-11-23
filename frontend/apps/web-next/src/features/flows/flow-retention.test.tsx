// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { makeFlow, makeStep } from "./flow-fixtures";
import { FlowSettings, SettingsSummary } from "./flow-settings";

const backend = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
const toastError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: backend }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/toast", async (importOriginal) => {
  const { toast } = await importOriginal<typeof import("@/lib/toast")>();
  return { toast: { ...toast, error: toastError } };
});

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
const policyKey = ["flows", "retention", "flow-1"];
const capRefusal = () =>
  new EneoApiError("The retention period is longer than the limit that applies here.", {
    status: 400,
    code: 9086,
    reason: "retention_exceeds_space",
    context: { cap_days: 7, cap_origin: "space" }
  });
const capText = "Ytan tillåter högst 7 dagar.";
/** The cap's status text, not the live region that speaks it on its own timer. */
const capStatus = () => screen.queryByText(capText, { ignore: "[aria-live], [aria-live] *" });

/** A GET that answers only when released, as a slow read in flight. */
function heldRead() {
  let release: (value: unknown) => void = () => {};
  backend.GET.mockReturnValueOnce(
    new Promise((resolve) => {
      release = resolve;
    })
  );
  return (value: unknown) => release(value);
}

/** Lets a released response, and the renders it causes, land. */
const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 20)));

afterEach(() => {
  cleanup();
  backend.GET.mockReset();
  backend.PUT.mockReset();
  toastError.mockReset();
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

  it("follows a later read of the space's time while the dialog is open", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    expect(await screen.findByText(/Från ytan: 60 dagar/)).toBeTruthy();
    backend.GET.mockResolvedValue(settings(null, { days: 14 }));
    await queryClient.refetchQueries({ queryKey: ["flows", "retention", "flow-1"] });
    expect(await screen.findByText(/Från ytan: 14 dagar/)).toBeTruthy();
  });

  it("says the space has no time when nothing applies", async () => {
    backend.GET.mockResolvedValue(settings(null, null));
    await openDialog();
    expect(screen.getByText(/Ytan har ingen tid/)).toBeTruthy();
  });

  it("names the space's cap next to the field when the backend refuses a longer time", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    let refuse: (error: unknown) => void = () => {};
    backend.PUT.mockReturnValue(
      new Promise((_, reject) => {
        refuse = reject;
      })
    );
    const days = (await openDialog()) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
    fireEvent.blur(days);
    const saveButton = screen.getByRole("button", { name: "Spara inställningar" });
    saveButton.focus();
    fireEvent.click(saveButton);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    // An edit while the save is pending does not take, so a late refusal marks the value sent.
    fireEvent.change(days, { target: { value: "5" } });
    fireEvent.blur(days);
    refuse(
      new EneoApiError("The retention period is longer than the limit that applies here.", {
        status: 400,
        code: 9086,
        reason: "retention_exceeds_space",
        context: { cap_days: 7, cap_origin: "space" }
      })
    );
    expect(await screen.findByText("Ytan tillåter högst 7 dagar.")).toBeTruthy();
    expect(days.value).toBe("10");
    expect(days.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(days);
    await waitFor(() => expect(days.readOnly).toBe(false));
    // A new value clears the refusal. The live region may still speak it, on its own timer.
    fireEvent.change(days, { target: { value: "5" } });
    fireEvent.blur(days);
    expect(
      screen.queryByText("Ytan tillåter högst 7 dagar.", { ignore: "[aria-live], [aria-live] *" })
    ).toBeNull();
    // Emptied, the field inherits the time the space last named, not the one read at open.
    fireEvent.change(days, { target: { value: "" } });
    fireEvent.blur(days);
    expect(screen.getByText(/Från ytan: 7 dagar/)).toBeTruthy();
  });

  it("keeps the space's time a refusal named when an older read lands after it", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockRejectedValue(capRefusal());
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    const release = heldRead();
    void queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await waitFor(() => expect(backend.GET).toHaveBeenCalledTimes(2));
    fireEvent.change(days, { target: { value: "10" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    expect(await screen.findByText(capText)).toBeTruthy();
    release(settings(null, { days: 60 }));
    await settle();
    fireEvent.change(days, { target: { value: "" } });
    fireEvent.blur(days);
    expect(screen.getByText(/Från ytan: 7 dagar/)).toBeTruthy();
  });

  it("keeps a saved time when an older read lands after the save", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = await screen.findByRole("spinbutton", { name: /Egen tid för det här flödet/ });
    const release = heldRead();
    void queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await waitFor(() => expect(backend.GET).toHaveBeenCalledTimes(2));
    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(screen.queryByRole("spinbutton")).toBeNull());
    release(settings(null, { days: 60 }));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const reopened = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    expect(reopened.value).toBe("30");
  });

  it("drops the cap error when a later read raises the space's time above the value", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockRejectedValue(capRefusal());
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    expect(await screen.findByText(capText)).toBeTruthy();
    backend.GET.mockResolvedValue(settings(null, { days: 14 }));
    await act(() => queryClient.refetchQueries({ queryKey: policyKey, exact: true }));
    await settle();
    expect(days.value).toBe("10");
    expect(days.getAttribute("aria-invalid")).toBeNull();
    expect(
      screen.queryByText(/Ytan tillåter högst/, { ignore: "[aria-live], [aria-live] *" })
    ).toBeNull();
  });

  it("keeps the cap message when a resubmit fails for another reason", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockRejectedValueOnce(capRefusal()).mockRejectedValueOnce(
      new EneoApiError("Internal error", { status: 500 })
    );
    const days = (await openDialog()) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
    fireEvent.blur(days);
    const saveButton = screen.getByRole("button", { name: "Spara inställningar" });
    fireEvent.click(saveButton);
    expect(await screen.findByText(capText)).toBeTruthy();
    await waitFor(() => expect(days.readOnly).toBe(false));
    fireEvent.click(saveButton);
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
    await settle();
    expect(capStatus()).toBeTruthy();
    expect(days.getAttribute("aria-invalid")).toBe("true");
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
