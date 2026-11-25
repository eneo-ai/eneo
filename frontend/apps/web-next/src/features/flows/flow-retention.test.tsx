// @vitest-environment jsdom
import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import type { Permission } from "@/lib/auth/permissions";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import {
  flushAnnouncements,
  recordAnnouncements,
  renderInApp,
  testAppContext,
  testQueryClient
} from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { makeFlow, makeStep } from "./flow-fixtures";
import { FlowSettings, SettingsSummary } from "./flow-settings";
import { flowKeys, flowQueryOptions, type FlowPublic } from "./flows-api";

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

const FIELD = "Flödets gallringstid";
const SAVE = "Spara";
const SAVE_AND_REMOVE = "Spara och ta bort";
/** The warning's title, which names a date that changes by the day. */
const WARNING_TITLE = /^Körningar avslutade omkring den .+ eller tidigare kan tas bort$/;
const warningShown = () =>
  screen.queryByText(WARNING_TITLE, { ignore: "[aria-live], [aria-live] *" }) !== null;
const PERSONAL =
  "Körningar i en personlig yta tas inte bort automatiskt. Flödets gallringstid används bara när en administratör rensar körningar för hand.";
const SPACE_HREF = "/spaces/space-1/settings?section=security#security";

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
  vi.useRealTimers();
  backend.GET.mockReset();
  backend.PUT.mockReset();
  toastError.mockReset();
});

function renderSettings(permissions: Permission[], mayChangeRetention = true) {
  return renderInApp(
    <FlowSettings
      flow={makeFlow({ run_history_retention: configured })}
      canEdit
      mayChangeRetention={mayChangeRetention}
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
      mayChangeRetention
      transcription={resources}
      onSave={vi.fn()}
    />
  ) : null;
}

/**
 * Presses the dialog's save button as a person does, the button taking focus first. It
 * says "Spara och ta bort" while a shorter time's warning shows, and one press saves.
 */
function pressSave() {
  const button = screen.getByRole("button", {
    name: new RegExp(`^(${SAVE}|${SAVE_AND_REMOVE})$`)
  });
  button.focus();
  fireEvent.click(button);
}

/**
 * Enter in the field, as a keyboard or a phone's Go key sends it, `repeat` while the key is
 * held. The dialog decides every Enter itself: the browser's own submit is always prevented.
 */
function pressEnter(field: HTMLElement, repeat = false) {
  expect(fireEvent.keyDown(field, { key: "Enter", code: "Enter", repeat })).toBe(false);
}

/** The unit the number's box draws after itself (CSS content), empty when it draws none. */
const drawnUnit = (field: HTMLElement) =>
  (field.closest("[style*='12rem']") as HTMLElement).style.getPropertyValue("--unit");

/** A press on the button as a pointer makes it, down, up and the click. */
function press(button: HTMLElement) {
  fireEvent.pointerDown(button);
  fireEvent.pointerUp(button);
  fireEvent.click(button);
}

async function openDialog() {
  renderSettings(["retention_manage"]);
  fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
  return (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
}

type Retention = FlowPublic["run_history_retention"];
/** The run history retention the server resolves for a space time and a flow time. */
function retentionOf(space: number | null, flow: number | null): Retention {
  return effectiveOf(
    flow === null ? null : { days: flow },
    space === null ? null : { days: space }
  ) as Retention;
}

/** The section on its own, as the flow's page shows it to someone reading. */
function renderSection(
  retention: Retention,
  {
    personalSpace = false,
    action,
    spaceHref
  }: { personalSpace?: boolean; action?: React.ReactNode; spaceHref?: string } = {}
) {
  renderInApp(
    <SettingsSummary
      flow={makeFlow({ run_history_retention: retention })}
      transcription={resources}
      personalSpace={personalSpace}
      retentionAction={action}
      spaceRetentionHref={spaceHref}
    />
  );
  return screen.getByRole("region", { name: "Gallring" });
}

/** What a row of the section says, by its label. */
function rowValue(section: HTMLElement, label: string) {
  return within(section).queryByText(label, { selector: "dt" })?.nextElementSibling?.textContent;
}

const changeButton = <Button label="Ändra gallring" size="sm" />;

describe("the retention section", () => {
  it("says nothing is removed while the space has no retention time, why, and where it is set", async () => {
    const section = renderSection(retentionOf(null, null), {
      action: changeButton,
      spaceHref: SPACE_HREF
    });
    expect(within(section).getByRole("heading", { level: 3, name: "Gallring" })).toBeTruthy();
    expect(within(section).getByText("Inga körningar tas bort automatiskt.")).toBeTruthy();
    // The icon tells the modes apart by its shape, not its colour.
    expect(section.querySelector("svg.lucide-ban[aria-hidden='true']")).toBeTruthy();
    expect(section.querySelector("svg.lucide-clock")).toBeNull();
    expect(within(section).getByText(messages.flows_retention_applies_none)).toBeTruthy();
    // On a line of its own, as the space's row has no link.
    const link = within(section).getByRole("link", {
      name: "Sätt gallringstid i ytans inställningar"
    });
    expect(link.getAttribute("href")).toBe(SPACE_HREF);
    expect(link.closest("dd")).toBeNull();
    expect(rowValue(section, "Flödets gallringstid")).toBe("Ingen");
    expect(rowValue(section, "Ytans gallringstid")).toBe("Ingen");
    expect(rowValue(section, "Gäller")).toBeUndefined();
    expect(within(section).getByRole("button", { name: "Ändra gallring" })).toBeTruthy();
    // The one who may change it is not told who does.
    expect(within(section).queryByText(/Gallringen ändras av/)).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("says a flow time of its own waits for the space's", async () => {
    const section = renderSection(retentionOf(null, 30), { spaceHref: SPACE_HREF });
    expect(within(section).getByText("Inga körningar tas bort automatiskt.")).toBeTruthy();
    expect(
      within(section).getByText(
        "Ytan har ingen gallringstid, så flödets gallringstid, 30 dagar, används bara när en administratör rensar körningar för hand. När ytan får en tid blir den taket, och avslutade körningar som startat medan ytan har en tid tas bort automatiskt när tiden har gått."
      )
    ).toBeTruthy();
    expect(
      within(section).getByRole("link", { name: "Sätt gallringstid i ytans inställningar" })
    ).toBeTruthy();
    expect(rowValue(section, "Flödets gallringstid")).toBe("30 dagar");
    expect(rowValue(section, "Ytans gallringstid")).toBe("Ingen");
    await expectNoAxeViolations(document.body);
  });

  it("says when runs that follow the space's time are removed, which ones, what goes and what stays", async () => {
    const section = renderSection(retentionOf(90, null), {
      action: changeButton,
      spaceHref: SPACE_HREF
    });
    expect(
      within(section).getByText(
        "Körningar kan tas bort automatiskt 90 dagar efter att de avslutades."
      )
    ).toBeTruthy();
    expect(section.querySelector("svg.lucide-clock[aria-hidden='true']")).toBeTruthy();
    expect(section.querySelector("svg.lucide-ban")).toBeNull();
    expect(rowValue(section, "Flödets gallringstid")).toBe("Ingen, följer ytans");
    // The link stands after the space's value, in its row.
    expect(rowValue(section, "Ytans gallringstid")).toBe(
      "90 dagar, taket för flödetÄndra i ytans inställningar"
    );
    const link = within(section).getByRole("link", { name: "Ändra i ytans inställningar" });
    expect(link.getAttribute("href")).toBe(SPACE_HREF);
    expect(link.closest("dd")).toBeTruthy();
    expect(rowValue(section, "Gäller")).toBe(
      "Flödets körningar som startar medan ytan har en gallringstid. Körningar som startade medan ytan saknade gallringstid, eller före uppgraderingen som införde automatisk gallring, tas inte bort automatiskt: de tas bort först när en administratör rensar körningar för hand. Varje körning räknas från när den avslutades, också om den misslyckades eller avbröts."
    );
    expect(rowValue(section, "Tas bort")).toBe(
      "Körningen med steg, transkript och de filer som ingen kvarvarande körning använder. Det går inte att återställa."
    );
    expect(rowValue(section, "Står kvar")).toBe(
      "Bland annat körningar som inte har avslutats, körningar med rättslig spärr och körningar som startade medan ytan saknade gallringstid eller före uppgraderingen som införde automatisk gallring."
    );
    await expectNoAxeViolations(document.body);
  });

  it("says a shorter flow time of its own applies under the space's cap", () => {
    const section = renderSection(retentionOf(90, 30), { spaceHref: SPACE_HREF });
    expect(
      within(section).getByText(
        "Körningar kan tas bort automatiskt 30 dagar efter att de avslutades."
      )
    ).toBeTruthy();
    expect(rowValue(section, "Flödets gallringstid")).toBe("30 dagar");
    expect(rowValue(section, "Ytans gallringstid")).toBe(
      "90 dagar, taket för flödetÄndra i ytans inställningar"
    );
    expect(rowValue(section, "Gäller")).toBeTruthy();
  });

  it("says the space's shorter time applies over a longer one saved on the flow", () => {
    const section = renderSection(retentionOf(90, 120));
    expect(
      within(section).getByText(
        "Körningar kan tas bort automatiskt 90 dagar efter att de avslutades."
      )
    ).toBeTruthy();
    expect(rowValue(section, "Flödets gallringstid")).toBe(
      "120 dagar sparat på flödet. Ytans kortare tid gäller."
    );
    // Without the right to change the space's time, its row has no link.
    expect(rowValue(section, "Ytans gallringstid")).toBe("90 dagar, taket för flödet");
    expect(within(section).queryByRole("link")).toBeNull();
  });

  it.each([
    ["with a flow time", 30, "30 dagar"],
    ["without one", null, "Ingen"]
  ])(
    "says runs in a personal space are not removed automatically, %s",
    async (_, flowDays, value) => {
      const section = renderSection(retentionOf(60, flowDays), {
        personalSpace: true,
        action: changeButton,
        spaceHref: SPACE_HREF
      });
      expect(within(section).getByText("Inga körningar tas bort automatiskt.")).toBeTruthy();
      expect(section.querySelector("svg.lucide-ban")).toBeTruthy();
      expect(within(section).getByText(PERSONAL)).toBeTruthy();
      expect(rowValue(section, "Flödets gallringstid")).toBe(value);
      // No row about the space's time, no link to it, and no rows of what is removed.
      expect(rowValue(section, "Ytans gallringstid")).toBeUndefined();
      expect(rowValue(section, "Gäller")).toBeUndefined();
      expect(within(section).queryByRole("link")).toBeNull();
      expect(within(section).getByRole("button", { name: "Ändra gallring" })).toBeTruthy();
      await expectNoAxeViolations(document.body);
    }
  );

  it("tells someone who may not change it who does, under the status line", async () => {
    const section = renderSection(retentionOf(90, null));
    const status = within(section).getByText(
      "Körningar kan tas bort automatiskt 90 dagar efter att de avslutades."
    );
    const who = within(section).getByText(
      "Gallringen ändras av den som administrerar ytan och har behörigheten ”Gallring – hantera regler”."
    );
    // The permission's name stays on one line.
    expect(who.textContent).toContain("”Gallring\u00a0–\u00a0hantera\u00a0regler”");
    expect(status.compareDocumentPosition(who) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(who.closest("dl")).toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
    expect(within(section).queryByRole("link")).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("puts who changes it after the explanation, and names a personal space's own rule", () => {
    const section = renderSection(retentionOf(null, null));
    const explanation = within(section).getByText(messages.flows_retention_applies_none);
    const who = within(section).getByText(/^Gallringen ändras av/);
    expect(
      explanation.compareDocumentPosition(who) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    cleanup();
    const personal = renderSection(retentionOf(null, 30), { personalSpace: true });
    expect(
      within(personal).getByText(
        "För att ändra gallringen behöver du kunna redigera flödet och ha behörigheten ”Gallring – hantera regler”."
      )
    ).toBeTruthy();
  });

  it("is a section of its own after the transcription, with the change in it, not by the settings heading", () => {
    const flow = makeFlow({
      steps: [makeStep(1, { input_type: "audio", output_mode: "transcribe_only" })],
      metadata_json: { wizard: { transcription_enabled: true } },
      run_history_retention: configured
    });
    renderInApp(
      <FlowSettings
        flow={flow}
        canEdit
        mayChangeRetention
        transcription={resources}
        onSave={vi.fn()}
        spaceRetentionHref={SPACE_HREF}
      />,
      { appContext: testAppContext({ permissions: ["retention_manage"] }) }
    );
    const section = screen.getByRole("region", { name: "Gallring" });
    const transcription = screen.getByRole("heading", { level: 3, name: "Transkribering" });
    expect(
      transcription.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    // The change is in the section; the settings heading keeps only its own.
    expect(within(section).getByRole("button", { name: "Ändra gallring" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Ändra gallring" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Ändra inställningar" })).toBeTruthy();
    // The old row among the other settings is gone.
    expect(screen.queryByText("Gallring av körhistorik")).toBeNull();
    expect(within(section).getByRole("link", { name: "Ändra i ytans inställningar" })).toBeTruthy();
  });

  it("leaves while the settings form is open, and comes back with it closed", () => {
    renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    expect(screen.queryByRole("region", { name: "Gallring" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ändra gallring" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(screen.getByRole("button", { name: "Ändra gallring" })).toBeTruthy();
  });
});

describe("flow retention", () => {
  it("offers the change only as the page decided, which is who may change it", () => {
    renderSettings(["retention_manage"], false);
    expect(screen.queryByRole("button", { name: "Ändra gallring" })).toBeNull();
    cleanup();
    renderSettings(["retention_manage"]);
    expect(screen.getByRole("button", { name: "Ändra gallring" })).toBeTruthy();
  });

  it("says what an empty field means, and saves a flow time", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const days = await openDialog();
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Ändra gallring" })).toBeTruthy();
    expect(within(dialog).getByText(messages.flows_retention_dialog_subtitle)).toBeTruthy();
    expect(
      screen.getByText(
        "Tomt fält: flödet följer ytans gallringstid, 60 dagar. Ange en kortare tid för att ta bort flödets körningar tidigare."
      )
    ).toBeTruthy();
    expect(days.placeholder).toBe("Följer ytan");
    // The unit is drawn after the field only with a value, so the placeholder reads alone.
    expect(drawnUnit(days)).toBe("");
    expect(within(dialog).getByRole("button", { name: SAVE })).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.change(days, { target: { value: "30" } });
    expect(drawnUnit(days)).toBe('"dagar"');
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
    expect(await screen.findByText(/följer ytans gallringstid, 60 dagar/)).toBeTruthy();
    backend.GET.mockResolvedValue(settings(null, { days: 14 }));
    await queryClient.refetchQueries({ queryKey: ["flows", "retention", "flow-1"] });
    expect(await screen.findByText(/följer ytans gallringstid, 14 dagar/)).toBeTruthy();
  });

  it("lets an untouched field follow a later read, and an untouched save sends nothing", async () => {
    backend.GET.mockResolvedValue(settings({ days: 3 }, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
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
    await waitFor(() => expect(screen.queryByRole("textbox", { name: FIELD })).toBeNull());
    release(settings({ days: 10 }, { days: 60 }));
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
  });

  it("keeps an edited flow time when a later read brings another", async () => {
    backend.GET.mockResolvedValue(settings({ days: 3 }, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 5 }, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "5" } });
    backend.GET.mockResolvedValue(settings({ days: 10 }, { days: 60 }));
    await queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await settle();
    expect(days.value).toBe("5");
    // 5 is shorter than the 10 read: the warning shows, though nothing was typed.
    expect(warningShown()).toBe(true);
    // The time that applies changed since the 5 was typed: the press is held.
    pressSave();
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
    expect(warningShown()).toBe(true);
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
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "" } });
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

  it("shows the warning with its date while a shorter time is typed, and a click on Spara och ta bort saves it", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-25T12:00:00"));
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const said = recordAnnouncements();
    const days = await openDialog();
    expect(
      within(screen.getByRole("dialog")).getByText(
        "Gäller flödets körningar som startar medan ytan har en gallringstid, inte äldre körningar. Varje körning räknas från när den avslutades."
      )
    ).toBeTruthy();
    expect(warningShown()).toBe(false);
    fireEvent.change(days, { target: { value: "3" } });
    fireEvent.change(days, { target: { value: "30" } });
    // Shown as it is typed, before any press, with the date the new time reaches back to.
    const title = screen.getByText(
      "Körningar avslutade omkring den 26 oktober 2026 eller tidigare kan tas bort",
      { ignore: "[aria-live], [aria-live] *" }
    );
    // The date stays on one line.
    expect(title.textContent).toContain("26\u00a0oktober\u00a02026");
    const banner = title.closest("[id]")!;
    expect(
      within(banner as HTMLElement).getByText(
        "Gallringstiden kortas från 60 dagar till 30 dagar. Kontrollen görs var femte minut. Körningen med steg, transkript och de filer som ingen kvarvarande körning använder tas bort och går inte att återställa. Datumet är ungefärligt: servern räknar från klockslaget då körningen avslutades, och körningen kan tas bort när den nya gallringstiden har gått sedan dess. Körningar med rättslig spärr och körningar som startade medan ytan saknade gallringstid, eller före uppgraderingen som införde automatisk gallring, står kvar."
      )
    ).toBeTruthy();
    expect(days.getAttribute("aria-describedby")).toContain(banner.getAttribute("id"));
    expect(backend.PUT).not.toHaveBeenCalled();
    // The button says what a press does, in the destructive look.
    expect(screen.queryByRole("button", { name: SAVE })).toBeNull();
    const button = screen.getByRole("button", { name: SAVE_AND_REMOVE });
    expect(button.getAttribute("data-variant")).toBe("destructive");
    // Said once, for the value left when the typing stopped, not for the 3 on the way.
    await waitFor(async () => {
      await flushAnnouncements();
      expect(said.filter((text) => WARNING_TITLE.test(text))).toEqual([
        "Körningar avslutade omkring den 26 oktober 2026 eller tidigare kan tas bort"
      ]);
    });
    await expectNoAxeViolations(document.body);

    // The warning is on screen: one click saves.
    fireEvent.click(button);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 30 },
      expected_effective_days: 60,
      expected_inherited_days: 60
    });
  });

  it("calls the warning's date approximate, as a run that finished late that day may not be due yet", async () => {
    // At 23:30, a run that finished at 23:45 on the date shown is due only in a quarter of an
    // hour: the server counts from the time the run finished, not from the date.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-25T23:30:00"));
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "30" } });
    const title = screen.getByText(
      "Körningar avslutade omkring den 26 oktober 2026 eller tidigare kan tas bort",
      { ignore: "[aria-live], [aria-live] *" }
    );
    const banner = title.closest("[id]") as HTMLElement;
    expect(
      within(banner).getByText(/Datumet är ungefärligt: servern räknar från klockslaget/)
    ).toBeTruthy();
  });

  it("drops the warning and its button when the time is no longer shorter", () => {
    backend.GET.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    return openDialog().then((days) => {
      fireEvent.change(days, { target: { value: "20" } });
      expect(warningShown()).toBe(true);
      fireEvent.change(days, { target: { value: "45" } });
      expect(warningShown()).toBe(false);
      const button = screen.getByRole("button", { name: SAVE });
      expect(button.getAttribute("data-variant")).toBe("primary");
    });
  });

  it("reads the field at every key, blanks around the number too", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: " 30 " } });
    expect(warningShown()).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: SAVE_AND_REMOVE }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body.policy).toEqual({ days: 30 });
  });

  it("holds the first Enter for a shorter time, so its warning is read, and saves on the next", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 20 }, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "30" } });
    // Enter right after the last digit: nothing is sent, the warning stays and the field keeps focus.
    pressEnter(days);
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
    expect(warningShown()).toBe(true);
    // A new value is held again on its first Enter.
    fireEvent.change(days, { target: { value: "20" } });
    pressEnter(days);
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
    pressEnter(days);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 20 },
      expected_effective_days: 60,
      expected_inherited_days: 60
    });
  });

  it("does nothing on the repeats of a held Enter, which still keep the browser from submitting", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "30" } });
    pressEnter(days);
    pressEnter(days, true);
    pressEnter(days, true);
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
    expect(warningShown()).toBe(true);
    // A new press saves.
    pressEnter(days);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
  });

  it("holds the first Enter again once the value is typed again, also the same value", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "30" } });
    pressEnter(days);
    fireEvent.change(days, { target: { value: "" } });
    fireEvent.change(days, { target: { value: "30" } });
    pressEnter(days);
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
    pressEnter(days);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
  });

  it("holds an Enter again when a read changes the time that applies after a held one", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "30" } });
    pressEnter(days);
    // Another administrator gave the flow 45 days; the dialog reads it.
    backend.GET.mockResolvedValue(settings({ days: 45 }, { days: 60 }));
    await act(() => queryClient.refetchQueries({ queryKey: policyKey, exact: true }));
    await settle();
    expect(days.value).toBe("30");
    pressEnter(days);
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
    expect(warningShown()).toBe(true);
    pressEnter(days);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 30 },
      expected_effective_days: 45,
      expected_inherited_days: 60
    });
  });

  it("holds a press when a read between its pointerdown and click makes the time shorter, and saves on a new press", async () => {
    backend.GET.mockResolvedValue(settings({ days: 3 }, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 5 }, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "5" } });
    expect(warningShown()).toBe(false);
    const button = screen.getByRole("button", { name: SAVE });
    fireEvent.pointerDown(button);
    // Another administrator gave the flow 10 days; the read lands while the button is down.
    backend.GET.mockResolvedValue(settings({ days: 10 }, { days: 60 }));
    await act(() => queryClient.refetchQueries({ queryKey: policyKey, exact: true }));
    await settle();
    fireEvent.pointerUp(button);
    fireEvent.click(button);
    await settle();
    // Nothing is sent: the warning shows now, and the button says what a press does.
    expect(backend.PUT).not.toHaveBeenCalled();
    expect(warningShown()).toBe(true);
    expect(screen.getByRole("button", { name: SAVE_AND_REMOVE })).toBe(button);
    press(button);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 5 },
      expected_effective_days: 10,
      expected_inherited_days: 60
    });
  });

  it("holds a press when the time that applies changes and comes back to the time typed against, and saves on a new press", async () => {
    backend.GET.mockResolvedValue(settings({ days: 10 }, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 5 }, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "5" } });
    expect(warningShown()).toBe(true);
    // A read gives the flow 3 days: 5 is no longer shorter.
    backend.GET.mockResolvedValue(settings({ days: 3 }, { days: 60 }));
    await act(() => queryClient.refetchQueries({ queryKey: policyKey, exact: true }));
    await settle();
    expect(warningShown()).toBe(false);
    const button = screen.getByRole("button", { name: SAVE });
    fireEvent.pointerDown(button);
    // While the button is down, a read gives the flow 10 days again.
    backend.GET.mockResolvedValue(settings({ days: 10 }, { days: 60 }));
    await act(() => queryClient.refetchQueries({ queryKey: policyKey, exact: true }));
    await settle();
    fireEvent.pointerUp(button);
    fireEvent.click(button);
    await settle();
    // The warning was not on screen when the press began: nothing is sent.
    expect(backend.PUT).not.toHaveBeenCalled();
    expect(warningShown()).toBe(true);
    press(screen.getByRole("button", { name: SAVE_AND_REMOVE }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 5 },
      expected_effective_days: 10,
      expected_inherited_days: 60
    });
  });

  it("holds an Enter again when the time that applies changes and comes back after a held one", async () => {
    backend.GET.mockResolvedValue(settings({ days: 10 }, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 5 }, { days: 60 }));
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "5" } });
    pressEnter(days);
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
    backend.GET.mockResolvedValue(settings({ days: 3 }, { days: 60 }));
    await act(() => queryClient.refetchQueries({ queryKey: policyKey, exact: true }));
    await settle();
    backend.GET.mockResolvedValue(settings({ days: 10 }, { days: 60 }));
    await act(() => queryClient.refetchQueries({ queryKey: policyKey, exact: true }));
    await settle();
    pressEnter(days);
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
    expect(warningShown()).toBe(true);
    pressEnter(days);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: { days: 5 },
      expected_effective_days: 10,
      expected_inherited_days: 60
    });
  });

  it("gives the field's description and error the dialog's width, and keeps the box for the number narrow", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    const days = await openDialog();
    /** Whether an element is inside the narrow box: an inline width of 12rem on it or above it. */
    const narrow = (element: Element) => element.closest("[style*='12rem']") !== null;
    const description = screen.getByText(/^Tomt fält: flödet följer ytans gallringstid/);
    expect(narrow(description)).toBe(false);
    expect(narrow(days)).toBe(true);
    // The unit is drawn by the number's box, so it stays beside it whatever is under it.
    expect(drawnUnit(days)).toBe("");
    fireEvent.change(days, { target: { value: "tre" } });
    pressSave();
    const error = await screen.findByText("Ange ett heltal från 1 till 2555.", {
      ignore: "[aria-live], [aria-live] *"
    });
    expect(narrow(error)).toBe(false);
    expect(drawnUnit(days)).toBe('"dagar"');
  });

  it("keeps the repeats of an Enter held on the save button from pressing it again", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "30" } });
    const button = screen.getByRole("button", { name: SAVE_AND_REMOVE });
    // A browser clicks a focused button on Enter, and again on each repeat of a held key:
    // the repeats are prevented, so a held press cannot be followed by a save. jsdom
    // clicks on no key, so this checks the prevention, not the click.
    expect(fireEvent.keyDown(button, { key: "Enter", code: "Enter", repeat: true })).toBe(false);
    expect(fireEvent.keyDown(button, { key: "Enter", code: "Enter" })).toBe(true);
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
  });

  it.each([
    ["in a personal space, empty", { personal: true, typed: null }],
    ["in a personal space, with a value", { personal: true, typed: "30" }],
    ["while the space has no time, empty", { personal: false, typed: null }],
    ["while the space has no time, with a value", { personal: false, typed: "5" }]
  ])("tells a screen reader the field's unit %s", async (_, { personal, typed }) => {
    backend.GET.mockResolvedValue(settings({ days: 45 }, personal ? { days: 60 } : null));
    renderInApp(
      <FlowSettings
        flow={makeFlow({ run_history_retention: retentionOf(personal ? 60 : null, 45) })}
        canEdit
        mayChangeRetention
        personalSpace={personal}
        transcription={resources}
        onSave={vi.fn()}
      />,
      { appContext: testAppContext({ permissions: ["retention_manage"] }) }
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = await screen.findByRole("textbox", { name: FIELD });
    fireEvent.change(days, { target: { value: typed ?? "" } });
    expect(screen.getByRole("textbox", { name: FIELD, description: /\bdagar\b/ })).toBe(days);
  });

  it("tells a screen reader the field's unit beside an error", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "tre" } });
    pressSave();
    expect(await screen.findByText("Ange ett heltal från 1 till 2555.")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: FIELD, description: /\bdagar\b/ })).toBe(days);
  });

  it("saves a time that removes nothing sooner on the first Enter", async () => {
    backend.GET.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 45 }, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "45" } });
    pressEnter(days);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body.policy).toEqual({ days: 45 });
  });

  it("saves a shorter time on the first tap on a phone, its warning already shown", async () => {
    setViewport("phone");
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockResolvedValue(settings({ days: 30 }, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "30" } });
    expect(warningShown()).toBe(true);
    const button = screen.getByRole("button", { name: SAVE_AND_REMOVE });
    fireEvent.pointerDown(button, { pointerType: "touch" });
    fireEvent.pointerUp(button, { pointerType: "touch" });
    fireEvent.click(button);
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body.policy).toEqual({ days: 30 });
    // The phone's Go key is an Enter: held for a shorter time as on a keyboard.
    cleanup();
    backend.PUT.mockClear();
    const again = await openDialog();
    fireEvent.change(again, { target: { value: "30" } });
    pressEnter(again);
    await settle();
    expect(backend.PUT).not.toHaveBeenCalled();
  });

  it("does not save a shorter time without its warning when another administrator changed the time meanwhile", async () => {
    const times: SavedTimes = { own: { days: 7 }, space: { days: 90 } };
    likeTheServer(times);
    const days = await openDialog();
    expect(days.value).toBe("7");
    // Another administrator raises the flow's time to 60 while the dialog is open.
    times.own = { days: 60 };
    fireEvent.change(days, { target: { value: "30" } });
    // Longer than the 7 the dialog read: no warning, sent on the first press, with the 7.
    expect(warningShown()).toBe(false);
    pressSave();
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
      screen.getByText(
        "Ytans gallringstid är 90 dagar. Flödets kan vara kortare, aldrig längre. Töm fältet för att följa ytan."
      )
    ).toBeTruthy();
    // Typed again, 30 is shorter than the 60 that applies now, so it warns before the press.
    fireEvent.change(days, { target: { value: "30" } });
    expect(warningShown()).toBe(true);
    expect(backend.PUT).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: SAVE_AND_REMOVE }));
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
    const days = await openDialog();
    times.own = { days: 60 };
    fireEvent.change(days, { target: { value: "30" } });
    pressSave();
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(days.value).toBe("60"));
    // Nothing typed since: Save closes the dialog and sends nothing.
    fireEvent.click(screen.getByRole("button", { name: SAVE }));
    await waitFor(() => expect(screen.queryByRole("textbox", { name: FIELD })).toBeNull());
    expect(backend.PUT).toHaveBeenCalledTimes(1);
    expect(times.own).toEqual({ days: 60 });
  });

  it("does not save a shorter time without its warning when another administrator gave the space a time meanwhile", async () => {
    // The flow keeps 60 days in a space without a time: no run is removed, so nothing warns.
    const times: SavedTimes = { own: { days: 60 }, space: null };
    likeTheServer(times);
    const days = await openDialog();
    expect(days.value).toBe("60");
    // Another administrator gives the space 90 days. 60 still applies, but runs are now removed.
    times.space = { days: 90 };
    fireEvent.change(days, { target: { value: "30" } });
    // Nothing warns on the times the dialog read: sent on the first press, with both of them.
    expect(warningShown()).toBe(false);
    pressSave();
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
    await waitFor(() => expect(screen.getByText(/^Ytans gallringstid är 90 dagar\./)).toBeTruthy());
    expect(days.value).toBe("60");
    // Typed again, under the space's 90, 30 shortens the 60 that applies, so it warns.
    fireEvent.change(days, { target: { value: "30" } });
    expect(warningShown()).toBe(true);
    expect(backend.PUT).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: SAVE_AND_REMOVE }));
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
    expect(warningShown()).toBe(false);
    // One press saves: no warning stands between it and the save.
    fireEvent.click(screen.getByRole("button", { name: SAVE }));
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    // It carries the time that applied as the server resolves it, also with no space time,
    // and the space's time as read.
    expect(backend.PUT.mock.calls[0]![1].body.expected_effective_days).toBe(
      effectiveOf(local, inherited).effective_days
    );
    expect(backend.PUT.mock.calls[0]![1].body.expected_inherited_days).toBe(
      inherited?.days ?? null
    );
  });

  it("says nothing is removed automatically while the space has no time, also with a flow time, and links to the space", async () => {
    backend.GET.mockResolvedValue(settings({ days: 30 }, null));
    renderInApp(
      <FlowSettings
        flow={makeFlow({ run_history_retention: retentionOf(null, 30) })}
        canEdit
        mayChangeRetention
        transcription={resources}
        onSave={vi.fn()}
        spaceRetentionHref={SPACE_HREF}
      />,
      { appContext: testAppContext({ permissions: ["retention_manage"] }) }
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(
        "Ytan har ingen gallringstid, så inga körningar tas bort automatiskt. Flödets tid används bara när en administratör rensar körningar för hand. När ytan får en tid blir den taket. Lämna fältet tomt för ingen egen tid."
      )
    ).toBeTruthy();
    // No placeholder: an empty field follows nothing.
    expect(days.placeholder).toBe("");
    const link = within(dialog).getByRole("link", {
      name: "Sätt gallringstid i ytans inställningar"
    });
    expect(link.getAttribute("href")).toBe(SPACE_HREF);
    fireEvent.change(days, { target: { value: "5" } });
    expect(warningShown()).toBe(false);
    await expectNoAxeViolations(document.body);
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
          mayChangeRetention
          personalSpace
          transcription={resources}
          onSave={vi.fn()}
          spaceRetentionHref={SPACE_HREF}
        />,
        { appContext: testAppContext({ permissions: ["retention_manage"] }) }
      );
      expect(screen.getByText(PERSONAL)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
      const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
      const dialog = screen.getByRole("dialog");
      expect(
        within(dialog).getByText(`${PERSONAL} ${messages.flows_retention_empty_none}`)
      ).toBeTruthy();
      expect(days.placeholder).toBe("");
      expect(within(dialog).queryByRole("link")).toBeNull();
      expect(screen.queryByText(/Ytan har ingen gallringstid/)).toBeNull();
      fireEvent.change(days, { target: { value: "30" } });
      expect(warningShown()).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: SAVE }));
      await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
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
    const days = await openDialog();
    expect(days.value).toBe("30");
    expect(
      screen.getByText(
        "Ytans gallringstid är 60 dagar. Flödets kan vara kortare, aldrig längre. Töm fältet för att följa ytan."
      )
    ).toBeTruthy();
    expect(drawnUnit(days)).toBe('"dagar"');
    await expectNoAxeViolations(document.body);
  });

  it("names the space's cap next to the field when the backend refuses a longer time", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    let refuse: (error: unknown) => void = () => {};
    backend.PUT.mockReturnValue(
      new Promise((_, reject) => {
        refuse = reject;
      })
    );
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "10" } });
    pressSave();
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    // An edit while the save is pending does not take, so a late refusal marks the value sent.
    fireEvent.change(days, { target: { value: "5" } });
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
    // The error names the cap; the line about the space's time does not say it twice, no
    // warning shows, and the button says Spara.
    expect(screen.queryByText(/Ytans gallringstid är/)).toBeNull();
    expect(warningShown()).toBe(false);
    expect(screen.getByRole("button", { name: SAVE })).toBeTruthy();
    await waitFor(() => expect(days.readOnly).toBe(false));
    // A new value clears the refusal. The live region may still speak it, on its own timer.
    fireEvent.change(days, { target: { value: "5" } });
    expect(
      screen.queryByText("Ytan tillåter högst 7 dagar.", { ignore: "[aria-live], [aria-live] *" })
    ).toBeNull();
    // Emptied, the field inherits the time the space last named, not the one read at open.
    fireEvent.change(days, { target: { value: "" } });
    expect(screen.getByText(/följer ytans gallringstid, 7 dagar/)).toBeTruthy();
  });

  it("keeps the space's time a refusal named when an older read lands after it", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockImplementation(refusedAt7);
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    const release = heldRead();
    void queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await waitFor(() => expect(backend.GET).toHaveBeenCalledTimes(2));
    fireEvent.change(days, { target: { value: "10" } });
    pressSave();
    expect(await screen.findByText(capText)).toBeTruthy();
    release(settings(null, { days: 60 }));
    await settle();
    fireEvent.change(days, { target: { value: "" } });
    expect(screen.getByText(/följer ytans gallringstid, 7 dagar/)).toBeTruthy();
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
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
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

  it("keeps the section's saved time when an older Flow read lands after the save", async () => {
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
    expect(screen.getByText(/tas bort automatiskt 7 dagar efter/)).toBeTruthy();
    void queryClient.refetchQueries({ queryKey: flowKeys.flow("flow-1"), exact: true });
    await waitFor(() => expect(flowReads).toBe(1));

    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = await screen.findByRole("textbox", { name: FIELD });
    fireEvent.change(days, { target: { value: "3" } });
    pressSave();
    await waitFor(() => expect(screen.queryByRole("textbox", { name: FIELD })).toBeNull());
    // The Flow is read again after the save; the read from before it lands last.
    await waitFor(() => expect(flowReads).toBe(2));
    await settle();
    releaseOlder(answered(makeFlow({ run_history_retention: byFlow(7) })));
    await settle();

    expect(screen.getByText(/tas bort automatiskt 3 dagar efter/)).toBeTruthy();
    expect(screen.queryByText(/tas bort automatiskt 7 dagar efter/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const reopened = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    expect(reopened.value).toBe("3");
  });

  it("reads the Flow again after a refusal, so the section shows the space's shorter time", async () => {
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
    expect(screen.getByText(/tas bort automatiskt 30 dagar efter/)).toBeTruthy();
    void queryClient.refetchQueries({ queryKey: flowKeys.flow("flow-1"), exact: true });
    await waitFor(() => expect(flowReads).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
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
    await waitFor(() => expect(screen.queryByRole("textbox", { name: FIELD })).toBeNull());
    expect(screen.getByText(/tas bort automatiskt 7 dagar efter/)).toBeTruthy();
    expect(screen.queryByText(/tas bort automatiskt 30 dagar efter/)).toBeNull();
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
    const days = await screen.findByRole("textbox", { name: FIELD });
    fireEvent.change(days, { target: { value: "30" } });
    pressSave();
    await waitFor(() => expect(screen.queryByRole("textbox", { name: FIELD })).toBeNull());
    // The read in flight saw the space's new time; the save's answer predates it.
    releaseOlder(newer());
    await settle();
    expect(screen.getByText(/tas bort automatiskt 7 dagar efter/)).toBeTruthy();
    expect(screen.queryByText(/tas bort automatiskt 30 dagar efter/)).toBeNull();

    // Opened again, the dialog names the space's shorter time beside the saved one.
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const reopened = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    expect(reopened.value).toBe("30");
    expect(
      within(screen.getByRole("dialog")).getByText(
        "30 dagar är sparat på flödet, men ytans gallringstid, 7 dagar, är taket och gäller. Ange en kortare tid eller töm fältet för att följa ytan."
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
    const days = await screen.findByRole("textbox", { name: FIELD });
    const release = heldRead();
    void queryClient.refetchQueries({ queryKey: policyKey, exact: true });
    await waitFor(() => expect(backend.GET).toHaveBeenCalledTimes(2));
    fireEvent.change(days, { target: { value: "30" } });
    pressSave();
    await waitFor(() => expect(screen.queryByRole("textbox", { name: FIELD })).toBeNull());
    release(settings(null, { days: 60 }));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const reopened = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    expect(reopened.value).toBe("30");
  });

  it("drops the cap error when a later read raises the space's time above the value", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    backend.PUT.mockImplementation(refusedAt7);
    const { queryClient } = renderSettings(["retention_manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Ändra gallring" }));
    const days = (await screen.findByRole("textbox", { name: FIELD })) as HTMLInputElement;
    fireEvent.change(days, { target: { value: "10" } });
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
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "10" } });
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
    expect(
      screen.getByText(
        "90 dagar är sparat på flödet, men ytans gallringstid, 60 dagar, är taket och gäller. Ange en kortare tid eller töm fältet för att följa ytan."
      )
    ).toBeTruthy();
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Rensa Flödets gallringstid" })
    );
    expect(days.value).toBe("");
    pressSave();
    await waitFor(() => expect(backend.PUT).toHaveBeenCalledTimes(1));
    expect(backend.PUT.mock.calls[0]![1].body).toEqual({
      policy: null,
      expected_effective_days: 60,
      expected_inherited_days: 60
    });
  });

  it("asks for a whole number in range on a press, and sends nothing", async () => {
    backend.GET.mockResolvedValue(settings(null, { days: 60 }));
    const days = await openDialog();
    fireEvent.change(days, { target: { value: "tre" } });
    pressSave();
    expect(await screen.findByText("Ange ett heltal från 1 till 2555.")).toBeTruthy();
    expect(days.getAttribute("aria-invalid")).toBe("true");
    expect(backend.PUT).not.toHaveBeenCalled();
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
