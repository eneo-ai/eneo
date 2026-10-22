// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeFlow } from "../flow-fixtures";
import { makeContract, makeInput, makeRunSummary } from "./run-fixtures";
import type { RunContract, RunPublic } from "./runs-api";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub: makeStub } = await import("../editor/testing/fixtures");
  api.stub = makeStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

import { StartRunDialog } from "./start-run-dialog";

const CONTRACT = "GET /api/v1/flows/{id}/run-contract/";
const START = "POST /api/v1/flows/{id}/runs/";

/** Answers runtime uploads as the core does, at once. */
class FakeUpload {
  static sent: { url: string; body: FormData }[] = [];
  status = 0;
  responseText = "";
  upload = { onprogress: null as ((event: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  private url = "";
  open(_method: string, url: string) {
    this.url = url;
  }
  setRequestHeader() {}
  getResponseHeader() {
    return null;
  }
  abort() {}
  send(body: FormData) {
    FakeUpload.sent.push({ url: this.url, body });
    queueMicrotask(() => {
      this.status = 201;
      const file = body.get("upload_file") as File;
      this.responseText = JSON.stringify({
        id: `file-${FakeUpload.sent.length}`,
        name: file.name,
        mimetype: file.type,
        size: file.size
      });
      this.onload?.();
    });
  }
}

const contract = makeContract({
  published_flow_version: 4,
  form_fields: [
    { name: "arende", label: "Ärende", type: "text", required: true, order: 1 },
    { name: "prio", label: "Prioritet", type: "select", options: ["Hög", "Låg"], order: 2 }
  ],
  steps_requiring_input: [makeInput({ step_id: "step-1", label: "Brevet", required: true })]
});

function Harness({ onStarted }: { onStarted: (run: RunPublic) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Kör
      </button>
      <StartRunDialog
        flow={makeFlow({ published_version: 4 })}
        open={open}
        onOpenChange={setOpen}
        onStarted={onStarted}
      />
    </>
  );
}

async function openDialog(withContract: RunContract = contract) {
  api.routes[CONTRACT] = () => ({ body: withContract });
  const onStarted = vi.fn();
  renderInApp(<Harness onStarted={onStarted} />);
  fireEvent.click(screen.getByRole("button", { name: "Kör" }));
  const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
  await within(dialog).findByLabelText(/^Ärende/);
  return { dialog, onStarted };
}

function pickFile(dialog: HTMLElement, file: File) {
  const input = dialog.querySelector<HTMLInputElement>("input[type=file]");
  if (!input) throw new Error("No file input");
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  api.routes = {};
  FakeUpload.sent = [];
  vi.stubGlobal("XMLHttpRequest", FakeUpload);
});

afterEach(() => {
  cleanup();
  api.stub.calls.length = 0;
  vi.unstubAllGlobals();
});

describe("StartRunDialog", () => {
  it("builds the form from the run contract", async () => {
    const { dialog } = await openDialog();
    expect(within(dialog).getByLabelText(/^Ärende/)).toBeTruthy();
    expect(within(dialog).getByText(/^Brevet/)).toBeTruthy();
    expect(within(dialog).getByText(/PDF · högst 10 MB per fil · högst 3 filer/)).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("says what is missing at each field and moves focus to the first", async () => {
    const { dialog } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_start_submit }));

    expect(await within(dialog).findByText("Fyll i Ärende.")).toBeTruthy();
    expect(within(dialog).getByText("Lägg till en fil i Brevet.")).toBeTruthy();
    const field = within(dialog).getByLabelText(/^Ärende/);
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field);
    expect(api.stub.calls.filter((call) => call.method === "POST")).toEqual([]);
    await expectNoAxeViolations(document.body);
  });

  it("refuses a file the step cannot take before sending it", async () => {
    const { dialog } = await openDialog();
    pickFile(dialog, new File(["x"], "bild.png", { type: "image/png" }));
    pickFile(
      dialog,
      new File([new Uint8Array(11 * 1024 * 1024)], "stor.pdf", { type: "application/pdf" })
    );

    expect(await within(dialog).findByText(/stor\.pdf/)).toBeTruthy();
    expect(within(dialog).getByText(/större än 10 MB/)).toBeTruthy();
    expect(FakeUpload.sent).toEqual([]);
  });

  it("uploads the files and starts the run pinned to the published version", async () => {
    const run = makeRunSummary({ id: "run-9", status: "queued" });
    api.routes[START] = () => ({ status: 201, body: run });
    const { dialog, onStarted } = await openDialog();
    fireEvent.change(within(dialog).getByLabelText(/^Ärende/), { target: { value: "Bygglov" } });
    pickFile(dialog, new File(["%PDF"], "brev.pdf", { type: "application/pdf" }));
    expect(await within(dialog).findByText(/Uppladdad/)).toBeTruthy();
    expect(FakeUpload.sent[0]?.url).toBe(
      "/api/eneo/api/v1/flows/flow-1/steps/step-1/runtime-files/"
    );

    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_start_submit }));

    await waitFor(() => expect(onStarted).toHaveBeenCalledWith(run));
    const call = api.stub.calls.find((entry) => `${entry.method} ${entry.path}` === START);
    expect(call?.init.body).toEqual({
      expected_flow_version: 4,
      input_payload_json: { arende: "Bygglov", prio: null },
      step_inputs: { "step-1": { file_ids: ["file-1"] } }
    });
    expect(
      (call?.init as { params?: { header?: Record<string, string> } }).params?.header?.[
        "Idempotency-Key"
      ]
    ).toBeTruthy();
  });

  it("shows the core's refusal at the field it names", async () => {
    api.routes[START] = () => ({
      status: 400,
      body: {
        message: "Missing required input field 'arende'.",
        code: "flow_input_required_field_empty",
        context: { field_name: "arende" }
      }
    });
    const { dialog } = await openDialog(
      makeContract({
        form_fields: [{ name: "arende", label: "Ärende", type: "text", required: false }]
      })
    );
    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_start_submit }));

    expect(
      await within(dialog).findByText(messages.flow_error_flow_input_required_field_empty)
    ).toBeTruthy();
    expect(document.activeElement).toBe(within(dialog).getByLabelText(/^Ärende/));
  });

  it("says why a flow that needs speaker labels cannot run", async () => {
    const { dialog } = await openDialog(
      makeContract({
        form_fields: [{ name: "arende", label: "Ärende", type: "text", required: false }],
        transcription: {
          live: { available: false },
          speaker_labels: {
            default: true,
            required: true,
            selectable: false,
            unavailable_reason: "not_chosen"
          }
        }
      })
    );
    expect(within(dialog).getByText(messages.flow_runs_speakers_blocked_title)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_start_submit }));
    expect(await within(dialog).findByText(messages.flow_runs_blocked)).toBeTruthy();
    expect(api.stub.calls.filter((call) => call.method === "POST")).toEqual([]);
  });
});
