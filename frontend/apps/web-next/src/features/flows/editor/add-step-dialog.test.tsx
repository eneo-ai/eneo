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
      "Anropa webbtjänst"
    ]);
    expect(
      within(dialog).getByText("Hamnar efter Steg 1: Sammanfatta, före Steg 2: Skriv svar")
    ).toBeTruthy();
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
      "Fyll i Word-mall",
      "Skicka körningens resultat"
    ]);
    expect(within(after.dialog).getByText("Hamnar efter Steg 1: Sammanfatta")).toBeTruthy();
    expect(within(after.dialog).queryByRole("radio", { name: "Gör text av data" })).toBeNull();
    cleanup();

    const first = await openDialog(1, textFlow);
    expect(rowsOf(first.dialog, messages.flow_add_step_recommended)).toEqual([
      "Sammanfatta",
      "Plocka ut uppgifter",
      "Transkribera ljud"
    ]);
    expect(within(first.dialog).getByText("Hamnar före Steg 1: Sammanfatta")).toBeTruthy();
    expect(rowsOf(first.dialog, messages.flow_add_step_more).at(-1)).toBe("Tomt steg");
    cleanup();

    const empty = await openDialog(1, makeFlow({ steps: [] }));
    expect(within(empty.dialog).getByText(messages.flow_add_step_lands_first)).toBeTruthy();
  });

  it("recommends sending the run's result after a document, and only where the core allows it", async () => {
    const wordFlow = makeFlow({
      steps: [makeStep({ output_type: "docx", output_mode: "render_verbatim" })]
    });
    api.routes[KINDS] = textKinds;
    const last = await openDialog(2, wordFlow);
    expect(rowsOf(last.dialog, messages.flow_add_step_recommended)).toEqual([
      "Skapa dokument",
      "Fyll i Word-mall",
      "Skicka körningens resultat"
    ]);
    cleanup();

    // Mid-flow the core refuses it: it is not recommended there.
    api.routes[KINDS] = ({ params }: { params: { query: { position: number } } }) => ({
      body: {
        flow_id: "flow-1",
        draft_revision: 4,
        insertions: [
          makeKindPlace(params.query.position, [
            makeKindOption("send_run_result", {
              refusals: [makeKindRefusal({ step_order: params.query.position })]
            })
          ])
        ],
        steps: []
      }
    });
    const middle = await openDialog(
      2,
      makeFlow({
        steps: [
          makeStep(),
          makeStep({ id: "step-2", step_order: 2, user_description: "Skriv svar" })
        ]
      })
    );
    expect(rowsOf(middle.dialog, messages.flow_add_step_recommended)).toContain("Sammanfatta");
    expect(rowsOf(middle.dialog, messages.flow_add_step_recommended)).not.toContain(
      "Skicka körningens resultat"
    );
  });

  it("starts on the first recommendation and adds it, named after it, with its instruction", async () => {
    const updated = makeFlow({ draft_revision: 5 });
    api.routes[EDITOR] = () => ({ body: updated });
    const { dialog, onSaved } = await openDialog(2);
    expect(
      (within(dialog).getByRole("radio", { name: "Gör text av data" }) as HTMLInputElement).checked
    ).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Gör text av data" }));

    // With the revision the add was fenced on, which tells the editor it was its own.
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(updated, 4));
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
    fireEvent.change(search, { target: { value: "ärendesystem" } });
    expect(
      within(dialog)
        .getAllByRole("radio")
        .map((radio) => radio.getAttribute("value"))
    ).toEqual(["send_http"]);
    // What is left, and what Enter adds, is said while focus stays in the search.
    await waitFor(() => expect(spoken()).toBe("1 stegtyp. Enter lägger till Anropa webbtjänst."));
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
        { target: { value: "ärendesystem" } }
      );
      expect(spoken()).not.toBe("Ingen stegtyp matchar ”ärendesystem”.");
      release();
      await waitFor(() => expect(spoken()).toBe("1 stegtyp. Enter lägger till Anropa webbtjänst."));
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
      ...(["speakers", "review", "fetch_http", "tool", "send_run_result", "send_http"] as const)
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

  it.each([
    ["a text step", textFlow, textKinds],
    ["a JSON step, where a plain POST is recommended", flow, null]
  ])(
    "ranks the step that sends the run's result first for “skicka” after %s",
    async (_, current, kinds) => {
      if (kinds) api.routes[KINDS] = kinds;
      const { dialog } = await openDialog(2, current);
      fireEvent.change(
        within(dialog).getByRole("textbox", { name: messages.flow_add_step_search }),
        {
          target: { value: "skicka" }
        }
      );
      const values = within(dialog)
        .getAllByRole("radio")
        .map((radio) => radio.getAttribute("value"));
      expect(values[0]).toBe("send_run_result");
      expect(values).toContain("send_http");
      const row = within(dialog).getByRole("radio", { name: "Skicka körningens resultat" });
      expect((row as HTMLInputElement).checked).toBe(true);
      expect(
        within(dialog).getByText(messages.flow_add_step_send_run_result_description)
      ).toBeTruthy();
      expect(within(dialog).getByRole("radio", { name: "Anropa webbtjänst" })).toBeTruthy();
    }
  );

  it("adds the step that sends the run's result with the receiver's fixed https address, in one save", async () => {
    const http = {
      url: "",
      auth: { mode: "none" },
      timeout_seconds: 30,
      body: { mode: "run_result" }
    };
    api.routes[KINDS] = () => ({
      body: {
        flow_id: "flow-1",
        draft_revision: 4,
        insertions: [
          makeKindPlace(2, [
            makeKindOption("send_run_result", {
              configuration: { output_mode: "http_post", output_config: http }
            })
          ])
        ],
        steps: []
      }
    });
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { dialog } = await openDialog(2, textFlow);
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView");
    fireEvent.click(within(dialog).getByRole("radio", { name: "Skicka körningens resultat" }));
    // The address field the choice adds to the footer shrinks the list: the chosen row is
    // brought back into view, not left under the footer (WCAG 2.4.11).
    await waitFor(() =>
      expect(
        scrolled.mock.contexts.map((element) => (element as HTMLElement).dataset.task)
      ).toContain("send_run_result")
    );
    expect(scrolled).toHaveBeenCalledWith({ block: "nearest" });
    scrolled.mockRestore();
    const submit = () =>
      within(dialog).getByRole("button", { name: "Lägg till Skicka körningens resultat" });
    const address = () => within(dialog).getByLabelText(/^Mottagarens adress/) as HTMLInputElement;

    fireEvent.click(submit());
    expect(
      await within(dialog).findByText(messages.flow_step_editor_http_url_missing)
    ).toBeTruthy();
    expect(document.activeElement).toBe(address());
    // The same rule as in the step: one fixed https address, which run data cannot choose.
    for (const url of [
      "http://intranet.example/resultat",
      "https://intranet.example/{{x}}",
      "ftp://intranet.example/resultat",
      "https://anna:hemligt@intranet.example/resultat"
    ]) {
      fireEvent.change(address(), { target: { value: url } });
      fireEvent.click(submit());
      expect(
        await within(dialog).findByText(messages.flow_step_editor_http_run_result_url_fixed)
      ).toBeTruthy();
      expect(within(dialog).queryByText(messages.flow_step_editor_http_url_invalid)).toBeNull();
      expect(address().getAttribute("aria-invalid")).toBe("true");
    }
    expect(api.stub.calls.filter((call) => call.method === "PATCH")).toEqual([]);

    fireEvent.change(address(), { target: { value: "https://intranet.example/resultat" } });
    fireEvent.click(submit());
    await waitFor(() => expect(sent()).toBeDefined());
    expect(sent()?.new_steps[0]).toMatchObject({
      name: "Skicka körningens resultat",
      configuration: {
        output_mode: "http_post",
        output_config: { url: "https://intranet.example/resultat", body: { mode: "run_result" } }
      }
    });
  });

  it.each([
    [
      "send_run_result",
      "Skicka körningens resultat",
      "run_result",
      "flow_step_editor_http_run_result_url_fixed"
    ],
    ["send_http", "Anropa webbtjänst", "auto", "flow_step_editor_http_url_invalid"]
  ] as const)(
    "puts the core's refusal of an address it alone checks at the field of %s, in its own words",
    async (kind, name, mode, message) => {
      api.routes[KINDS] = () => ({
        body: {
          flow_id: "flow-1",
          draft_revision: 4,
          insertions: [
            makeKindPlace(2, [
              makeKindOption(kind, {
                configuration: {
                  output_mode: "http_post",
                  output_config: { url: "", auth: { mode: "none" }, body: { mode } }
                }
              })
            ])
          ],
          steps: []
        }
      });
      // An address the dialog lets through, which the core still refuses (its host, say).
      api.routes[EDITOR] = () => ({
        status: 400,
        body: {
          message: "Step 2: output_config validation failed",
          code: "typed_io_http_invalid_config",
          context: { field: "output_config.url", http_error: "HTTP_INVALID_URL" },
          eneo_error_code: 9000
        }
      });
      const { dialog } = await openDialog(2, textFlow);
      fireEvent.click(within(dialog).getByRole("radio", { name }));
      const address = within(dialog).getByRole("textbox", {
        name: /^(Mottagarens adress|Adress att skicka till)/
      }) as HTMLInputElement;
      expect(address.type).toBe("url");
      fireEvent.change(address, { target: { value: "https://intranet.example/in" } });
      fireEvent.click(within(dialog).getByRole("button", { name: `Lägg till ${name}` }));
      expect(await within(dialog).findByText(messages[message])).toBeTruthy();
      expect(document.activeElement).toBe(address);
    }
  );

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
