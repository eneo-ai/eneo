// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
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

function Harness({ position, onSaved }: { position: number; onSaved: (flow: FlowPublic) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Lägg till
      </button>
      <AddStepDialog
        flow={flow}
        position={position}
        open={open}
        onOpenChange={setOpen}
        onSaved={onSaved}
      />
    </>
  );
}

async function openDialog(position = 2) {
  const onSaved = vi.fn();
  renderInApp(<Harness position={position} onSaved={onSaved} />);
  fireEvent.click(screen.getByRole("button", { name: "Lägg till" }));
  const dialog = await screen.findByRole("dialog", { name: messages.flow_step_editor_add_title });
  return { dialog, onSaved };
}

/** The core's answer at place 2: Word or PDF before step 3, which reads JSON, is refused. */
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
  it("is a named form dialog whose kinds that do not fit say why, as the core judges them", async () => {
    const { dialog } = await openDialog();
    const documentKind = await within(dialog).findByRole("radio", {
      name: new RegExp(messages.flow_step_editor_kind_document)
    });
    const asked = api.stub.calls.find((call) => `${call.method} ${call.path}` === KINDS);
    expect(asked?.init.params).toEqual({ path: { id: "flow-1" }, query: { position: 2 } });
    expect(
      (documentKind as HTMLInputElement).disabled ||
        documentKind.getAttribute("aria-disabled") === "true"
    ).toBe(true);
    // The document and the template kind give Word or PDF, which step 3 cannot read as JSON.
    expect(
      within(dialog).getAllByText(
        new RegExp(messages.flow_step_editor_kind_block_next_step_cannot_read)
      )
    ).toHaveLength(2);
    await expectNoAxeViolations(document.body);
  });

  it("adds an AI step where it was asked for, with the configuration the core gives it", async () => {
    const updated = makeFlow({ draft_revision: 5 });
    api.routes[EDITOR] = () => ({ body: updated });
    const { dialog, onSaved } = await openDialog(2);
    await within(dialog).findByRole("radio", {
      name: new RegExp(messages.flow_step_editor_kind_ai)
    });
    const name = within(dialog).getByLabelText(/^Stegnamn/) as HTMLInputElement;
    expect(name.value).toBe(messages.flow_step_editor_kind_ai_name);
    fireEvent.change(name, { target: { value: "Bedöm ärendet" } });
    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.flow_step_editor_add_submit })
    );

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(updated));
    const body = api.stub.calls.find((call) => `${call.method} ${call.path}` === EDITOR)?.init.body;
    expect(body).toEqual({
      expected_revision: 4,
      definition: {},
      new_steps: [{ name: "Bedöm ärendet", configuration: ai.configuration, assistant: {} }],
      step_order: [{ step_id: "step-1" }, { new_step: 0 }, { step_id: "step-2" }]
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("explains a taken name at the field instead of adding", async () => {
    const { dialog } = await openDialog();
    await within(dialog).findByRole("radio", {
      name: new RegExp(messages.flow_step_editor_kind_ai)
    });
    const name = within(dialog).getByLabelText(/^Stegnamn/) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "skriv svar" } });
    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.flow_step_editor_add_submit })
    );

    expect(await within(dialog).findByText(messages.flow_step_editor_name_taken)).toBeTruthy();
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(name);
    expect(api.stub.calls.filter((call) => call.method === "PATCH")).toEqual([]);
  });

  it("asks for the address of a step that fetches over HTTP", async () => {
    const { dialog } = await openDialog();
    fireEvent.click(
      await within(dialog).findByRole("radio", {
        name: new RegExp(`^${messages.flow_step_editor_kind_fetch_http}`)
      })
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.flow_step_editor_add_submit })
    );

    expect(
      await within(dialog).findByText(messages.flow_step_editor_http_url_missing)
    ).toBeTruthy();
    expect(document.activeElement).toBe(within(dialog).getByLabelText(/^Adress att hämta från/));
  });

  it("cannot add while the core has not answered for the place, and offers a retry", async () => {
    api.routes[KINDS] = () => ({ status: 500, body: { message: "Fel", code: "internal" } });
    const { dialog } = await openDialog();
    expect(await within(dialog).findByRole("button", { name: messages.retry })).toBeTruthy();
    const submit = within(dialog).getByRole("button", {
      name: messages.flow_step_editor_add_submit
    }) as HTMLButtonElement;
    expect(submit.disabled || submit.getAttribute("aria-disabled") === "true").toBe(true);
    expect(within(dialog).queryByRole("radio")).toBeNull();
  });
});
