// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { SpaceProvider } from "@/features/spaces/use-space";
import type { FlowPublic } from "./step-types";
import {
  makeFlow,
  makeKindOption,
  makeKindPlace,
  makeKindRefusal,
  makeStep
} from "./testing/fixtures";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("./testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub: makeStub } = await import("./testing/fixtures");
  api.stub = makeStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

import { AddStepDialog } from "./add-step-dialog";

const EDITOR = "PATCH /api/v1/flows/{id}/editor/";
const KINDS = "GET /api/v1/flows/{id}/step-kinds/";

/** Step 1, "Sammanfatta", answers in JSON; step 2, "Skriv svar", reads it. */
const flow = makeFlow({
  steps: [
    makeStep({ output_type: "json" }),
    makeStep({
      id: "step-2",
      assistant_id: "assistant-2",
      step_order: 2,
      user_description: "Skriv svar",
      input_source: "previous_step",
      input_type: "json"
    })
  ]
});
/** One step, "Sammanfatta", that answers in text. */
const textFlow = makeFlow({ steps: [makeStep({ output_type: "text" })] });

function Harness({
  position,
  onSaved,
  current
}: {
  position: number;
  onSaved: (flow: FlowPublic) => void;
  current: FlowPublic;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Lägg till
      </button>
      <AddStepDialog
        flow={current}
        position={position}
        open={open}
        onOpenChange={setOpen}
        onSaved={onSaved}
      />
    </>
  );
}

async function openDialog(position = 2, current = flow, { rows = true, personal = false } = {}) {
  const onSaved = vi.fn();
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], makeSpace({ overrides: { personal } }));
  renderInApp(
    <SpaceProvider routeId="space-1">
      <Harness position={position} onSaved={onSaved} current={current} />
    </SpaceProvider>,
    { queryClient }
  );
  fireEvent.click(screen.getByRole("button", { name: "Lägg till" }));
  const dialog = await screen.findByRole("dialog", { name: messages.flow_step_editor_add_title });
  if (rows) await within(dialog).findAllByRole("radio");
  return { dialog, onSaved };
}

/** The visible names of a group's rows, in order. */
function rowsOf(dialog: HTMLElement, group: string) {
  return within(within(dialog).getByRole("radiogroup", { name: group }))
    .getAllByRole("radio")
    .map((radio) => document.getElementById(radio.getAttribute("aria-labelledby")!)?.textContent);
}

type Sent = {
  new_steps: { name: string; configuration: Record<string, unknown>; assistant: unknown }[];
};

/** What the polite live region says now. */
function spoken() {
  return document.querySelector("[data-astryx-live-region='polite']")?.textContent;
}

function sent(): Sent | undefined {
  return api.stub.calls.find((call) => `${call.method} ${call.path}` === EDITOR)?.init.body as
    Sent | undefined;
}

/** The core's answer for `textFlow`: every kind allowed, reading text. */
function textKinds({ params }: { params: { query: { position: number } } }) {
  return {
    body: {
      flow_id: "flow-1",
      draft_revision: 4,
      insertions: [makeKindPlace(params.query.position)],
      steps: []
    }
  };
}

/** The core's answer at place 2: Word before step 2, which reads JSON, is refused. */
const readsJson = makeKindRefusal({ step_order: 3, step_id: "step-2" });
const ai = makeKindOption("ai", { configuration: { input_type: "json" } });
const place = makeKindPlace(2, [
  ai,
  makeKindOption("document", { refusals: [readsJson] }),
  makeKindOption("template", { refusals: [readsJson] })
]);

beforeEach(() => {
  api.routes = {
    "GET /api/v1/flows/{id}/tool-options": () => ({
      body: { items: [], security_classifications_enabled: false }
    }),
    [KINDS]: () => ({
      body: { flow_id: "flow-1", draft_revision: 4, insertions: [place], steps: [] }
    })
  };
});
afterEach(() => {
  cleanup();
  api.stub.calls.length = 0;
});

describe("AddStepDialog", () => {
  it("recommends what reads JSON after a JSON step and folds what the core refuses, with why", async () => {
    const { dialog } = await openDialog(2);
    const asked = api.stub.calls.find((call) => `${call.method} ${call.path}` === KINDS);
    expect(asked?.init.params).toEqual({ path: { id: "flow-1" }, query: { position: 2 } });
    expect(rowsOf(dialog, messages.flow_add_step_recommended)).toEqual([
      "Gör text av data",
      "Skicka via HTTP"
    ]);
    expect(within(dialog).getByText("Hamnar efter Steg 1: Sammanfatta")).toBeTruthy();
    // Word cannot stand before a step that reads JSON: one folded line, then the reasons.
    expect(within(dialog).queryByRole("radio", { name: "Skapa dokument" })).toBeNull();
    fireEvent.click(within(dialog).getByText("2 stegtyper går inte att lägga till här"));
    expect(
      within(dialog).getAllByText(messages.flow_step_editor_kind_block_next_step_cannot_read)
    ).toHaveLength(2);
    await expectNoAxeViolations(document.body);
  });

  it("recommends text tasks after a text step, the input kinds first, never data into text", async () => {
    api.routes[KINDS] = textKinds;
    const after = await openDialog(2, textFlow);
    expect(rowsOf(after.dialog, messages.flow_add_step_recommended)).toEqual([
      "Sammanfatta",
      "Förbättra text",
      "Plocka ut uppgifter",
      "Klassificera",
      "Skapa dokument",
      "Fyll i Word-mall"
    ]);
    expect(within(after.dialog).queryByRole("radio", { name: "Gör text av data" })).toBeNull();
    cleanup();

    const first = await openDialog(1, textFlow);
    expect(rowsOf(first.dialog, messages.flow_add_step_recommended)).toEqual([
      "Sammanfatta",
      "Plocka ut uppgifter",
      "Transkribera ljud"
    ]);
    expect(within(first.dialog).getByText(messages.flow_add_step_lands_first)).toBeTruthy();
    expect(rowsOf(first.dialog, messages.flow_add_step_more).at(-1)).toBe("Tomt steg");
  });

  it("starts on the first recommendation and adds it, named after it, with its instruction", async () => {
    const updated = makeFlow({ draft_revision: 5 });
    api.routes[EDITOR] = () => ({ body: updated });
    const { dialog, onSaved } = await openDialog(2);
    expect(
      (within(dialog).getByRole("radio", { name: "Gör text av data" }) as HTMLInputElement).checked
    ).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Gör text av data" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(updated));
    expect(sent()).toEqual({
      expected_revision: 4,
      definition: {},
      new_steps: [
        {
          name: "Gör text av data",
          configuration: ai.configuration,
          assistant: { prompt: { text: messages.flow_template_render_text_prompt } }
        }
      ],
      step_order: [{ step_id: "step-1" }, { new_step: 0 }, { step_id: "step-2" }]
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("names the confirm after the choice and adds a row on double-click, under a free name", async () => {
    api.routes[KINDS] = textKinds;
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { dialog } = await openDialog(2, textFlow);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Klassificera" }));
    expect(within(dialog).getByRole("button", { name: "Lägg till Klassificera" })).toBeTruthy();

    fireEvent.doubleClick(within(dialog).getByText("Sammanfatta"));
    await waitFor(() => expect(sent()).toBeDefined());
    expect(sent()?.new_steps[0]).toMatchObject({
      name: "Sammanfatta 2",
      assistant: { prompt: { text: messages.flow_template_summarize_prompt } }
    });
  });

  it("finds a row by a word people use, and Enter in the search adds the match", async () => {
    api.routes[KINDS] = textKinds;
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { dialog } = await openDialog(2, textFlow);
    const search = within(dialog).getByRole("textbox", { name: messages.flow_add_step_search });
    fireEvent.change(search, { target: { value: "webhook" } });
    expect(
      within(dialog)
        .getAllByRole("radio")
        .map((radio) => radio.getAttribute("value"))
    ).toEqual(["send_http"]);
    // What is left, and what Enter adds, is said while focus stays in the search.
    await waitFor(() => expect(spoken()).toBe("1 stegtyp. Enter lägger till Skicka via HTTP."));
    fireEvent.change(search, { target: { value: "zzz" } });
    await waitFor(() => expect(spoken()).toBe("Ingen stegtyp matchar ”zzz”."));

    // "pdf" finds the document row and makes it a PDF.
    fireEvent.change(search, { target: { value: "pdf" } });
    expect(within(dialog).getAllByText("Text → PDF").length).toBeGreaterThan(0);
    fireEvent.keyDown(search, { key: "Enter" });
    await waitFor(() => expect(sent()).toBeDefined());
    expect(sent()?.new_steps[0]).toMatchObject({
      name: "Skapa dokument",
      configuration: { output_type: "pdf" }
    });
  });

  it("starts afresh in the search each time it opens", async () => {
    api.routes[KINDS] = textKinds;
    const { dialog } = await openDialog(2, textFlow);
    const search = () =>
      within(dialog).getByRole("textbox", { name: messages.flow_add_step_search });
    await waitFor(() => expect(document.activeElement).toBe(search()));
    fireEvent.change(search(), { target: { value: "webhook" } });
    fireEvent.click(within(dialog).getByRole("button", { name: messages.cancel }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Lägg till" }));
    await within(dialog).findByRole("radio", { name: "Sammanfatta" });
    expect((search() as HTMLInputElement).value).toBe("");
    await waitFor(() => expect(document.activeElement).toBe(search()));
  });

  it("adds the row Enter is pressed on, also one focused in the other group", async () => {
    api.routes[KINDS] = textKinds;
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { dialog } = await openDialog(2, textFlow);
    const compose = within(dialog).getByRole("radio", { name: "Sätt ihop text" });
    expect((compose as HTMLInputElement).checked).toBe(false);
    compose.focus();
    fireEvent.keyDown(compose, { key: "Enter" });
    await waitFor(() => expect(sent()).toBeDefined());
    expect(sent()?.new_steps[0]?.name).toBe("Sätt ihop text");
  });

  it("says what a search typed while the kinds load finds once they are in", async () => {
    api.routes[KINDS] = textKinds;
    const get = api.stub.client.GET;
    let release = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    api.stub.client.GET = (async (...args: Parameters<typeof get>) => {
      if (args[0] === KINDS.slice(4)) await gate;
      return get(...args);
    }) as typeof get;
    try {
      const { dialog } = await openDialog(2, textFlow, { rows: false });
      fireEvent.change(
        within(dialog).getByRole("textbox", { name: messages.flow_add_step_search }),
        { target: { value: "webhook" } }
      );
      expect(spoken()).not.toBe("Ingen stegtyp matchar ”webhook”.");
      release();
      await waitFor(() => expect(spoken()).toBe("1 stegtyp. Enter lägger till Skicka via HTTP."));
    } finally {
      api.stub.client.GET = get;
    }
  });

  it("shows and focuses what a row Enter lands on still needs, without adding it", async () => {
    api.routes[KINDS] = textKinds;
    const { dialog } = await openDialog(2, textFlow);
    const fetch = within(dialog).getByRole("radio", { name: "Hämta via HTTP" });
    fetch.focus();
    fireEvent.keyDown(fetch, { key: "Enter" });

    expect(
      await within(dialog).findByText(messages.flow_step_editor_http_url_missing)
    ).toBeTruthy();
    expect((fetch as HTMLInputElement).checked).toBe(true);
    expect(document.activeElement).toBe(within(dialog).getByLabelText(/^Adress att hämta från/));
    expect(api.stub.calls.filter((call) => call.method === "PATCH")).toEqual([]);
  });

  it("folds the tool step in a personal space, saying why, instead of sending the person to an administrator", async () => {
    api.routes[KINDS] = textKinds;
    const { dialog } = await openDialog(2, textFlow, { personal: true });
    expect(within(dialog).queryByRole("radio", { name: messages.flow_add_step_tool })).toBeNull();
    fireEvent.click(within(dialog).getByText("1 stegtyp går inte att lägga till här"));
    expect(within(dialog).getByText(messages.flow_step_editor_tools_personal)).toBeTruthy();
    expect(within(dialog).queryByText(messages.flow_step_editor_tools_none)).toBeNull();
  });

  it("says that nothing can be added here, with the reasons open, when the core refuses all", async () => {
    const refusal = makeKindRefusal({ message: "Nej." });
    const kinds = [
      ...(["ai", "structured", "compose", "document", "template", "transcribe"] as const),
      ...(["speakers", "review", "fetch_http", "tool", "send_http"] as const)
    ];
    api.routes[KINDS] = () => ({
      body: {
        flow_id: "flow-1",
        draft_revision: 4,
        insertions: [
          makeKindPlace(
            2,
            kinds.map((kind) => makeKindOption(kind, { refusals: [refusal] }))
          )
        ],
        steps: []
      }
    });
    const { dialog } = await openDialog(2, textFlow, { rows: false });
    expect(await within(dialog).findByText(messages.flow_add_step_none_allowed)).toBeTruthy();
    expect(within(dialog).queryByText(/matchar/)).toBeNull();
    await waitFor(() => expect(spoken()).toBe(messages.flow_add_step_none_allowed));
    // The reasons show without opening the fold.
    expect(
      within(dialog)
        .getByRole("button", { name: /stegtyper går inte att lägga till här/ })
        .getAttribute("aria-expanded")
    ).toBe("true");
  });

  it("puts focus in the search after reloading a draft that moved on", async () => {
    api.routes[KINDS] = textKinds;
    api.routes[EDITOR] = () => ({
      status: 400,
      body: { message: "Stale", code: "stale_revision", eneo_error_code: 9000 }
    });
    api.routes["GET /api/v1/flows/{id}/"] = () => ({ body: { ...textFlow, draft_revision: 5 } });
    const { dialog } = await openDialog(2, textFlow);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Sammanfatta" }));
    const reload = await within(dialog).findByRole("button", {
      name: messages.flow_step_editor_reload
    });
    reload.focus();
    fireEvent.click(reload);
    await waitFor(() =>
      expect(
        within(dialog).queryByRole("button", { name: messages.flow_step_editor_reload })
      ).toBeNull()
    );
    expect(document.activeElement).toBe(
      within(dialog).getByRole("textbox", { name: messages.flow_add_step_search })
    );
  });

  it("asks for the address of a step that fetches over HTTP before adding it", async () => {
    const { dialog } = await openDialog(2);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Hämta via HTTP" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Hämta via HTTP" }));

    expect(
      await within(dialog).findByText(messages.flow_step_editor_http_url_missing)
    ).toBeTruthy();
    expect(document.activeElement).toBe(within(dialog).getByLabelText(/^Adress att hämta från/));
    expect(api.stub.calls.filter((call) => call.method === "PATCH")).toEqual([]);
  });

  it("cannot add while the core has not answered for the place, and offers a retry", async () => {
    api.routes[KINDS] = () => ({ status: 500, body: { message: "Fel", code: "internal" } });
    const { dialog } = await openDialog(2, flow, { rows: false });
    expect(await within(dialog).findByRole("button", { name: messages.retry })).toBeTruthy();
    const submit = within(dialog).getByRole("button", {
      name: messages.flow_step_editor_add_title
    }) as HTMLButtonElement;
    expect(submit.disabled || submit.getAttribute("aria-disabled") === "true").toBe(true);
    expect(within(dialog).queryByRole("radio")).toBeNull();
  });
});
