// @vitest-environment jsdom
import { useQuery } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import type { Permission } from "@/lib/auth/permissions";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { makeFlow, makeStep } from "./flow-fixtures";
import { FlowSettings, SettingsSummary } from "./flow-settings";
import { flowKeys, flowQueryOptions } from "./flows-api";

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
type Days = { days: number } | null;
/** What applies, as the server resolves it: the Flow's own time when it is at most the Space's. */
const effectiveOf = (local: Days, inherited: Days) => {
  const contributors = { space: inherited, flow: local };
  if (!local && !inherited)
    return { state: "off", source: "none", effective_days: null, contributors };
  const flowWins = local !== null && (inherited === null || local.days <= inherited.days);
  return {
    state: "configured",
    source: flowWins ? "flow" : "space",
    effective_days: flowWins ? local.days : inherited!.days,
    contributors
  };
};
const settings = (local: Days, inherited: Days) =>
  answered({
    scope: "flow",
    scope_id: "flow-1",
    local_policy: local,
    inherited_policy: inherited,
    effective: effectiveOf(local, inherited)
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
/** A PUT the server refuses at a space time of 7, which its later reads then name. */
const refusedAt7 = () => {
  backend.GET.mockResolvedValue(settings(null, { days: 7 }));
  return Promise.reject(capRefusal());
};
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

type SavedTimes = { own: Days; space: Days };
type FlowTimeBody = {
  policy: Days;
  expected_effective_days?: number | null;
  expected_inherited_days?: number | null;
};
/**
 * Answers as the server does. `times` is what it has now, and a test changes it as another
 * administrator would: a save that carries another time that applied, or another space time,
 * than the server has is refused, each compared only when it is sent.
 */
function likeTheServer(times: SavedTimes) {
  backend.GET.mockImplementation(() => Promise.resolve(settings(times.own, times.space)));
  backend.PUT.mockImplementation((_path: string, { body }: { body: FlowTimeBody }) => {
    const applies = effectiveOf(times.own, times.space).effective_days;
    if (
      ("expected_effective_days" in body && body.expected_effective_days !== applies) ||
      ("expected_inherited_days" in body &&
        body.expected_inherited_days !== (times.space?.days ?? null))
    ) {
      return Promise.reject(
        new EneoApiError("The retention time has changed.", {
          status: 409,
          code: 9087,
          reason: "retention_time_changed",
          context: { current_days: applies }
        })
      );
    }
    times.own = body.policy;
    return Promise.resolve(settings(times.own, times.space));
  });
}

afterEach(() => {
  cleanup();
  backend.GET.mockReset();
  backend.PUT.mockReset();
  toastError.mockReset();
});

function renderSettings(permissions: Permission[], setsSpaceRetention = true) {
  return renderInApp(
    <FlowSettings
      flow={makeFlow({ run_history_retention: configured })}
      canEdit
      setsSpaceRetention={setsSpaceRetention}
      transcription={resources}
      onSave={vi.fn()}
    />,
    { appContext: testAppContext({ permissions }) }
  );
}

/** The page reads the flow from its detail entry, as the summary does here. */
function CachedFlowSettings() {
  const flow = useQuery(flowQueryOptions(browserApi, "flow-1")).data;
  return flow ? (
    <FlowSettings
      flow={flow}
      canEdit
      setsSpaceRetention
      transcription={resources}
      onSave={vi.fn()}
    />
  ) : null;
}

/**
 * Presses Save as a person does, the button taking focus first. A shorter time is
 * sent on the press after its warning, so the second press follows when it shows.
 */
function pressSave() {
  const button = screen.getByRole("button", { name: "Spara inställningar" });
  button.focus();
  fireEvent.click(button);
  // The status text, not the live region that speaks it on its own timer.
  if (screen.queryByText(/Spara igen/, { ignore: "[aria-live], [aria-live] *" })) {
    button.focus();
    fireEvent.click(button);
  }
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

  it("does not offer the change without the right to set retention in the flow's space", () => {
    renderSettings(["retention_manage"], false);
    expect(screen.queryByRole("button", { name: "Ändra gallring" })).toBeNull();
  });

  it("shows the space's time while the field is empty, and saves a flow time", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const days = await openDialog();
    expect(screen.getByText(/Från ytan: 60 dagar/)).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    pressSave();
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 30 },
      expected_effective_days: 60,
      expected_inherited_days: 60
    });
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

  it("lets an untouched field follow a later read, and an untouched save sends nothing", async () => {
    backend.GET.mockResolvedValue(settings({ days: 3 }, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    expect(days.value).toBe("3");
    // Another admin saved 10 meanwhile; the dialog reads it.
    backend.GET.mockResolvedValue(settings({ days: 10 }, { days: 60 }));
    await queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await waitFor(() => expect(days.value).toBe("10"));
    // Nothing was edited, so there is nothing to save, not even while a read is in flight.
    const release = heldRead();
    void queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await waitFor(() => expect(backend.GET).toHaveBeenCalledTimes(3));
    pressSave();
    await waitFor(() => expect(screen.queryByRole("spinbutton")).toBeNull());
    release(settings({ days: 10 }, { days: 60 }));
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
  });

  it("keeps an edited flow time when a later read brings another", async () => {
    backend.GET.mockResolvedValue(settings({ days: 3 }, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 5 }, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "5" } });
    fireEvent.blur(days);
    backend.GET.mockResolvedValue(settings({ days: 10 }, { days: 60 }));
    await queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await settle();
    expect(days.value).toBe("5");
    pressSave();
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 5 },
      // The time the later read brought is what the save replaces.
      expected_effective_days: 10,
      expected_inherited_days: 60
    });
  });

  it("keeps a deliberately cleared field when a later read brings a time", async () => {
    backend.GET.mockResolvedValue(settings({ days: 3 }, { days: 60 }));
    backend.PUT.mockResolvedValue(settings(null, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "" } });
    fireEvent.blur(days);
    backend.GET.mockResolvedValue(settings({ days: 10 }, { days: 60 }));
    await queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await settle();
    expect(days.value).toBe("");
    pressSave();
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: null,
      expected_effective_days: 10,
      expected_inherited_days: 60
    });
  });

  it("warns before a shorter time is saved, and saves it on the next press", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    // The first press shows the warning instead of saving: it was not on screen before.
    const warning = await screen.findByText(
      "Körningar som redan är äldre än den nya tiden räknas som förfallna och tas bort vid en kommande kontroll. Det går inte att återställa. Spara igen för att använda den."
    );
    expect(days.getAttribute("aria-describedby")).toContain(
      warning.closest("[id]")?.getAttribute("id")
    );
    expect(backend.PUT).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 30 },
      expected_effective_days: 60,
      expected_inherited_days: 60
    });
  });

  it("does not save a shorter time without its warning when another administrator changed the time meanwhile", async () => {
    const times: SavedTimes = { own: { days: 7 }, space: { days: 90 } };
    likeTheServer(times);
    const days = (await openDialog()) as HTMLInputElement;
    expect(days.value).toBe("7");
    // Another administrator raises the flow's time to 60 while the dialog is open.
    times.own = { days: 60 };
    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    // Longer than the 7 the dialog read: sent on the first press, with the 7 it was compared with.
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    // Refused: the 60 stands.
    await settle();
    expect(times.own).toEqual({ days: 60 });
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 30 },
      expected_effective_days: 7,
      expected_inherited_days: 90
    });
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
    expect(toastError.mock.calls[0]![0]).toBe(messages.eneo_error_9087);
    // The draft is dropped and the times are read again: the focused field shows the 60.
    await waitFor(() => expect(days.value).toBe("60"));
    expect(document.activeElement).toBe(days);
    expect(
      screen.getByText("Ytans tid är 90 dagar. Flödets tid kan inte vara längre.")
    ).toBeTruthy();
    // Typed again, 30 is shorter than the 60 that applies now, so it warns first.
    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    expect(await screen.findByText(/Spara igen för att använda den/)).toBeTruthy();
    expect(backend.PUT).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(2));
    expect(backend.PUT.mock.calls[1]![1].body).toEqual({
      policy: { days: 30 },
      expected_effective_days: 60,
      expected_inherited_days: 90
    });
    expect(times.own).toEqual({ days: 30 });
  });

  it("saves nothing after a refusal until a time is typed again", async () => {
    const times: SavedTimes = { own: { days: 7 }, space: { days: 90 } };
    likeTheServer(times);
    const days = (await openDialog()) as HTMLInputElement;
    times.own = { days: 60 };
    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(days.value).toBe("60"));
    // Nothing typed since: Save closes the dialog and sends nothing.
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(screen.queryByRole("spinbutton")).toBeNull());
    expect(backend.PUT).toHaveBeenCalledTimes(1);
    expect(times.own).toEqual({ days: 60 });
  });

  it("does not save a shorter time without its warning when another administrator gave the space a time meanwhile", async () => {
    // The flow keeps 60 days in a space without a time: no run is removed, so nothing warns.
    const times: SavedTimes = { own: { days: 60 }, space: null };
    likeTheServer(times);
    const days = (await openDialog()) as HTMLInputElement;
    expect(days.value).toBe("60");
    // Another administrator gives the space 90 days. 60 still applies, but runs are now removed.
    times.space = { days: 90 };
    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    // Nothing warns on the times the dialog read: sent on the first press, with both of them.
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    // Refused: the 60 stands.
    await settle();
    expect(times.own).toEqual({ days: 60 });
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 30 },
      expected_effective_days: 60,
      expected_inherited_days: null
    });
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
    // The draft is dropped and the times are read again: the field shows the flow's 60, and
    // the line under it names the space's new time.
    await waitFor(() =>
      expect(
        screen.getByText("Ytans tid är 90 dagar. Flödets tid kan inte vara längre.")
      ).toBeTruthy()
    );
    expect(days.value).toBe("60");
    // Typed again, under the space's 90, 30 shortens the 60 that applies, so it warns.
    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    expect(await screen.findByText(/Spara igen för att använda den/)).toBeTruthy();
    expect(backend.PUT).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(2));
    expect(backend.PUT.mock.calls[1]![1].body).toEqual({
      policy: { days: 30 },
      expected_effective_days: 60,
      expected_inherited_days: 90
    });
    expect(times.own).toEqual({ days: 30 });
  });

  it.each([
    ["a longer flow time", { days: 30 }, { days: 60 }, "45"],
    ["a time while the space has none", null, null, "30"],
    ["a shorter flow time while the space has none", { days: 30 }, null, "20"]
  ])("saves %s on the first press, without a warning", async (_, local, inherited, typed) => {
    backend.GET.mockResolvedValue(settings(local, inherited));
    backend.PUT.mockResolvedValue(settings({ days: Number(typed) }, inherited));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: typed } });
    fireEvent.blur(days);
    // One press saves: no warning stands between it and the save.
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/tas bort vid en kommande kontroll/)).toBeNull();
    // It carries the time that applied as the server resolves it, also with no space time,
    // and the space's time as read.
    expect(backend.PUT.mock.calls[0]![1].body.expected_effective_days).toBe(
      effectiveOf(local, inherited).effective_days
    );
    expect(backend.PUT.mock.calls[0]![1].body.expected_inherited_days).toBe(
      inherited?.days ?? null
    );
  });

  it("says automatic removal is paused while the space has no time, also with a flow time", async () => {
    backend.GET.mockResolvedValue(settings({ days: 30 }, null));
    await openDialog();
    expect(
      screen.getByText(
        "Ytan har ingen tid, så den automatiska gallringen står still tills ytan har en tid."
      )
    ).toBeTruthy();
  });

  it("says in the summary that a flow time waits for the space's", () => {
    renderInApp(
      <SettingsSummary
        flow={makeFlow({
          run_history_retention: {
            state: "configured",
            source: "flow",
            effective_days: 30,
            contributors: { space: null, flow: { days: 30 } }
          }
        })}
        transcription={resources}
      />
    );
    expect(screen.getByText(/30 dagar, satt på flödet/)).toBeTruthy();
    expect(
      screen.getByText(
        "Ytan har ingen tid, så den automatiska gallringen står still tills ytan har en tid."
      )
    ).toBeTruthy();
  });

  it.each([
    ["with a time stored on the space", { days: 60 }],
    ["without a time", null]
  ])(
    "says runs in a personal space are not removed automatically, %s, and never warns",
    async (_, spaceTime) => {
      backend.GET.mockResolvedValue(settings({ days: 45 }, spaceTime));
      backend.PUT.mockResolvedValue(settings({ days: 30 }, spaceTime));
      renderInApp(
        <FlowSettings
          flow={makeFlow({
            run_history_retention: {
              state: "configured",
              source: "flow",
              effective_days: 45,
              contributors: { space: spaceTime, flow: { days: 45 } }
            }
          })}
          canEdit
          setsSpaceRetention
          personalSpace
          transcription={resources}
          onSave={vi.fn()}
        />,
        { appContext: testAppContext({ permissions: ["retention_manage"] }) }
      );
      const personal =
        "Körningar i personliga ytor tas inte bort automatiskt i den här versionen. Flödets tid gäller då bara en administratörs uttryckliga rensning.";
      expect(screen.getByText(personal)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
      const days = await screen.findByRole("spinbutton", { name: /Egen tid för det här flödet/ });
      expect(screen.getAllByText(personal)).toHaveLength(2);
      expect(screen.queryByText(/tas bort automatiskt när/)).toBeNull();
      expect(screen.queryByText(/Ytan har ingen tid/)).toBeNull();
      fireEvent.change(days, { target: { value: "30" } });
      fireEvent.blur(days);
      fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
      await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
      expect(screen.queryByText(/tas bort vid en kommande kontroll/)).toBeNull();
      // The flow's 45 applies, as the server resolves it, though nothing warns here; the
      // space's time goes as read, also one stored on a personal space.
      expect(backend.PUT.mock.calls[0]![1].body.expected_effective_days).toBe(45);
      expect(backend.PUT.mock.calls[0]![1].body.expected_inherited_days).toBe(
        spaceTime?.days ?? null
      );
    }
  );

  it("names the space's time beside a flow time of its own", async () => {
    backend.GET.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const days = (await openDialog()) as HTMLInputElement;
    expect(days.value).toBe("30");
    expect(
      screen.getByText("Ytans tid är 60 dagar. Flödets tid kan inte vara längre.")
    ).toBeTruthy();
    await expectNoAxeViolations(document.body);
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
    pressSave();
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    // An edit while the save is pending does not take, so a late refusal marks the value sent.
    fireEvent.change(days, { target: { value: "5" } });
    fireEvent.blur(days);
    // The server is at 7 when it refuses, and the dialog reads its times again.
    backend.GET.mockResolvedValue(settings(null, { days: 7 }));
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
    // The error names the cap; the line about the space's time does not say it twice.
    expect(screen.queryByText(/Ytans tid är/)).toBeNull();
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
    backend.PUT.mockImplementation(refusedAt7);
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
    pressSave();
    expect(await screen.findByText(capText)).toBeTruthy();
    release(settings(null, { days: 60 }));
    await settle();
    fireEvent.change(days, { target: { value: "" } });
    fireEvent.blur(days);
    expect(screen.getByText(/Från ytan: 7 dagar/)).toBeTruthy();
  });

  it("reads the times again after a refusal, so a space time raised meanwhile clears the error", async () => {
    // What the server holds; each read after the opening one answers only when released.
    let space = 60;
    const held: (() => void)[] = [];
    backend.GET.mockImplementation(() => {
      const answer = settings(null, { days: space });
      if (backend.GET.mock.calls.length === 1) return Promise.resolve(answer);
      return new Promise((resolve) => held.push(() => resolve(answer)));
    });
    let refuse: (error: unknown) => void = () => {};
    backend.PUT.mockReturnValue(
      new Promise((_, reject) => {
        refuse = reject;
      })
    );
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
    fireEvent.blur(days);
    pressSave();
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));

    // The server refuses at 7; another admin then raises the space's time to 14, and a read
    // in flight sees it before the refusal arrives.
    space = 14;
    void queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await waitFor(() => expect(held).toHaveLength(1));
    refuse(capRefusal());
    expect(await screen.findByText(capText)).toBeTruthy();
    await settle();
    expect(capStatus()).toBeTruthy();

    // Every read still held answers 14: the error goes, the value and the focus stay.
    held.forEach((release) => release());
    await settle();
    expect(capStatus()).toBeNull();
    expect(days.value).toBe("10");
    expect(days.getAttribute("aria-invalid")).toBeNull();
    expect(document.activeElement).toBe(days);
    expect(backend.PUT).toHaveBeenCalledTimes(1);
  });

  it("keeps the summary's saved time when an older Flow read lands after the save", async () => {
    const byFlow = (days: number) =>
      ({
        state: "configured",
        source: "flow",
        effective_days: days,
        contributors: { space: { days: 60 }, flow: { days } }
      }) as const;
    const queryClient = testQueryClient();
    queryClient.setQueryData(
      flowKeys.flow("flow-1"),
      makeFlow({ run_history_retention: byFlow(7) })
    );
    // What the server holds; the first Flow read is in flight across the save, later ones
    // answer at once.
    let own = 7;
    let releaseOlder: (value: unknown) => void = () => {};
    let flowReads = 0;
    backend.GET.mockImplementation((path: string) => {
      if (path !== "/api/v1/flows/{id}/")
        return Promise.resolve(settings({ days: own }, { days: 60 }));
      flowReads += 1;
      if (flowReads > 1)
        return Promise.resolve(answered(makeFlow({ run_history_retention: byFlow(own) })));
      return new Promise((resolve) => {
        releaseOlder = resolve;
      });
    });
    backend.PUT.mockImplementation(() => {
      own = 3;
      return Promise.resolve(
        answered({
          scope: "flow",
          scope_id: "flow-1",
          local_policy: { days: 3 },
          inherited_policy: { days: 60 },
          effective: byFlow(3)
        })
      );
    });
    renderInApp(<CachedFlowSettings />, {
      queryClient,
      appContext: testAppContext({ permissions: ["retention_manage"] })
    });
    expect(screen.getByText(/7 dagar, satt på flödet/)).toBeTruthy();
    void queryClient.refetchQueries({ queryKey: flowKeys.flow("flow-1"), exact: true });
    await waitFor(() => expect(flowReads).toBe(1));

    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = await screen.findByRole("spinbutton", { name: /Egen tid för det här flödet/ });
    fireEvent.change(days, { target: { value: "3" } });
    fireEvent.blur(days);
    pressSave();
    await waitFor(() => expect(screen.queryByRole("spinbutton")).toBeNull());
    // The Flow is read again after the save; the read from before it lands last.
    await waitFor(() => expect(flowReads).toBe(2));
    await settle();
    releaseOlder(answered(makeFlow({ run_history_retention: byFlow(7) })));
    await settle();

    expect(screen.getByText(/3 dagar, satt på flödet/)).toBeTruthy();
    expect(screen.queryByText(/7 dagar, satt på flödet/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const reopened = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    expect(reopened.value).toBe("3");
  });

  it("reads the Flow again after a refusal, so the summary shows the space's shorter time", async () => {
    const retention = (source: "flow" | "space", days: number, space: number) =>
      ({
        state: "configured",
        source,
        effective_days: days,
        contributors: { space: { days: space }, flow: { days: 30 } }
      }) as const;
    const queryClient = testQueryClient();
    queryClient.setQueryData(
      flowKeys.flow("flow-1"),
      makeFlow({ run_history_retention: retention("flow", 30, 60) })
    );
    // The server is at 7 when it refuses, and the dialog reads its times again.
    let space = 60;
    // Each Flow read answers only when released: one from before the save, one after it.
    const flowReads: ((value: unknown) => void)[] = [];
    backend.GET.mockImplementation((path: string) =>
      path === "/api/v1/flows/{id}/"
        ? new Promise((resolve) => flowReads.push(resolve))
        : Promise.resolve(settings({ days: 30 }, { days: space }))
    );
    backend.PUT.mockImplementation(() => {
      space = 7;
      return Promise.reject(capRefusal());
    });
    renderInApp(<CachedFlowSettings />, {
      queryClient,
      appContext: testAppContext({ permissions: ["retention_manage"] })
    });
    expect(screen.getByText(/30 dagar, satt på flödet/)).toBeTruthy();
    void queryClient.refetchQueries({ queryKey: flowKeys.flow("flow-1"), exact: true });
    await waitFor(() => expect(flowReads).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
    fireEvent.blur(days);
    pressSave();
    // The cap shows without waiting for the Flow, which is read again behind it.
    expect(await screen.findByText(capText)).toBeTruthy();
    await waitFor(() => expect(flowReads).toHaveLength(2));

    // The new read lands while the dialog is open: the error, the value and the focus stay.
    flowReads[1]!(answered(makeFlow({ run_history_retention: retention("space", 7, 7) })));
    await settle();
    expect(capStatus()).toBeTruthy();
    expect(days.value).toBe("10");
    expect(document.activeElement).toBe(days);

    // The read from before the refusal lands last and does not bring the Flow's 30 back.
    flowReads[0]!(answered(makeFlow({ run_history_retention: retention("flow", 30, 60) })));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(screen.queryByRole("spinbutton")).toBeNull());
    expect(screen.getByText(/7 dagar, ärvt från ytan/)).toBeTruthy();
    expect(screen.queryByText(/30 dagar, satt på flödet/)).toBeNull();
  });

  it("reads the Flow and its times again after a save, so a newer space time shows", async () => {
    const retention = (source: "flow" | "space", days: number, space: number, flow: number) =>
      ({
        state: "configured",
        source,
        effective_days: days,
        contributors: { space: { days: space }, flow: { days: flow } }
      }) as const;
    // What the server holds: another admin lowers the space's time to 7 once the save commits.
    let space = 60;
    let own: number | null = null;
    const newer = () => answered(makeFlow({ run_history_retention: retention("space", 7, 7, 30) }));
    const queryClient = testQueryClient();
    queryClient.setQueryData(
      flowKeys.flow("flow-1"),
      makeFlow({ run_history_retention: configured })
    );
    // The first Flow read is in flight across the save; later ones answer at once.
    let releaseOlder: (value: unknown) => void = () => {};
    let flowReads = 0;
    backend.GET.mockImplementation((path: string) => {
      if (path !== "/api/v1/flows/{id}/")
        return Promise.resolve(settings(own === null ? null : { days: own }, { days: space }));
      flowReads += 1;
      if (flowReads > 1) return Promise.resolve(newer());
      return new Promise((resolve) => {
        releaseOlder = resolve;
      });
    });
    backend.PUT.mockImplementation(() => {
      own = 30;
      const saved = answered({
        scope: "flow",
        scope_id: "flow-1",
        local_policy: { days: 30 },
        inherited_policy: { days: space },
        effective: retention("flow", 30, space, 30)
      });
      space = 7;
      return Promise.resolve(saved);
    });
    renderInApp(<CachedFlowSettings />, {
      queryClient,
      appContext: testAppContext({ permissions: ["retention_manage"] })
    });
    void queryClient.refetchQueries({ queryKey: flowKeys.flow("flow-1"), exact: true });
    await waitFor(() => expect(flowReads).toBe(1));

    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = await screen.findByRole("spinbutton", { name: /Egen tid för det här flödet/ });
    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    pressSave();
    await waitFor(() => expect(screen.queryByRole("spinbutton")).toBeNull());
    // The read in flight saw the space's new time; the save's answer predates it.
    releaseOlder(newer());
    await settle();
    expect(screen.getByText(/7 dagar, ärvt från ytan/)).toBeTruthy();
    expect(screen.queryByText(/30 dagar, satt på flödet/)).toBeNull();

    // Opened again, the dialog names the space's shorter time beside the saved one.
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const reopened = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    expect(reopened.value).toBe("30");
    expect(
      within(screen.getByRole("dialog")).getByText(
        "30 dagar sparat på flödet. Ytans kortare tid gäller."
      )
    ).toBeTruthy();
  });

  it("keeps a saved time when an older read lands after the save", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    // After the save the server holds 30, and the times are read again.
    backend.PUT.mockImplementation(() => {
      backend.GET.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
      return Promise.resolve(settings({ days: 30 }, { days: 60 }));
    });
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = await screen.findByRole("spinbutton", { name: /Egen tid för det här flödet/ });
    const release = heldRead();
    void queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await waitFor(() => expect(backend.GET).toHaveBeenCalledTimes(2));
    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.blur(days);
    pressSave();
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
    backend.PUT.mockImplementation(refusedAt7);
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("spinbutton", {
      name: /Egen tid för det här flödet/
    })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
    fireEvent.blur(days);
    pressSave();
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
    backend.PUT.mockImplementationOnce(refusedAt7).mockRejectedValueOnce(
      new EneoApiError("Internal error", { status: 500 })
    );
    const days = (await openDialog()) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
    fireEvent.blur(days);
    pressSave();
    expect(await screen.findByText(capText)).toBeTruthy();
    await waitFor(() => expect(days.readOnly).toBe(false));
    pressSave();
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
    pressSave();
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: null,
      expected_effective_days: 60,
      expected_inherited_days: 60
    });
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
