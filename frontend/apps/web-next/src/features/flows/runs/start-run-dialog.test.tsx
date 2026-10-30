// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeFlow } from "../flow-fixtures";
import { makeContract, makeInput, makeRunDetail, makeRunSummary } from "./run-fixtures";
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
const LIST = "GET /api/v1/flows/{id}/runs/";
const DETAIL = "GET /api/v1/flows/{id}/runs/{run_id}/";

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
  getAllResponseHeaders() {
    return "";
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

function Harness({
  onStarted,
  metadata = null
}: {
  onStarted: (run: RunPublic) => void;
  metadata?: Record<string, unknown> | null;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Kör
      </button>
      <StartRunDialog
        flow={makeFlow({ published_version: 4, metadata_json: metadata })}
        open={open}
        onOpenChange={setOpen}
        onStarted={onStarted}
      />
    </>
  );
}

async function openDialog(
  withContract: RunContract = contract,
  metadata: Record<string, unknown> | null = null
) {
  api.routes[CONTRACT] = () => ({ body: withContract });
  const onStarted = vi.fn();
  renderInApp(<Harness onStarted={onStarted} metadata={metadata} />);
  fireEvent.click(screen.getByRole("button", { name: "Kör" }));
  const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
  await within(dialog).findByLabelText(/^Ärende/);
  return { dialog, onStarted };
}

function button(dialog: HTMLElement, name: string) {
  return within(dialog).getByRole("button", { name });
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
    fireEvent.click(button(dialog, messages.flow_runs_summary_next));

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

  it.each(["audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"])(
    "uploads WAV declared as %s through the contract-backed file picker",
    async (mimetype) => {
      const { dialog } = await openDialog({
        ...contract,
        steps_requiring_input: [
          makeInput({
            input_format: "audio",
            accepted_mimetypes: ["audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"]
          })
        ]
      });
      const file = new File(["RIFF....WAVEfmt "], "meeting.wav", { type: mimetype });
      pickFile(dialog, file);

      expect(await within(dialog).findByText(/Uppladdad/)).toBeTruthy();
      expect(FakeUpload.sent[0]?.body.get("upload_file")).toBe(file);
      expect(within(dialog).getByText(/^WAV · högst/)).toBeTruthy();
    }
  );

  it("uploads the files, sums up what is sent and starts the run pinned to the published version", async () => {
    const run = makeRunSummary({ id: "run-9", status: "queued" });
    api.routes[START] = () => ({ status: 201, body: run });
    const { dialog, onStarted } = await openDialog();
    fireEvent.change(within(dialog).getByLabelText(/^Ärende/), { target: { value: "Bygglov" } });
    pickFile(dialog, new File(["%PDF"], "brev.pdf", { type: "application/pdf" }));
    expect(await within(dialog).findByText(/Uppladdad/)).toBeTruthy();
    expect(FakeUpload.sent[0]?.url).toBe(
      "/api/eneo/api/v1/flows/flow-1/steps/step-1/runtime-files/"
    );

    fireEvent.click(button(dialog, messages.flow_runs_summary_next));

    // Nothing is sent until the person has seen what will be.
    const heading = within(dialog).getByRole("heading", { name: messages.flow_runs_summary_title });
    expect(document.activeElement).toBe(heading);
    const summary = within(dialog).getByRole("region", { name: messages.flow_runs_summary_title });
    expect(within(summary).getByText("Ärende")).toBeTruthy();
    expect(within(summary).getByText("Bygglov")).toBeTruthy();
    expect(within(summary).getByText("Brevet")).toBeTruthy();
    expect(within(summary).getByText("brev.pdf")).toBeTruthy();
    // The optional field left empty carries no answer.
    expect(within(summary).queryByText("Prioritet")).toBeNull();
    // The form waits, hidden, with its files and recordings.
    expect(within(dialog).queryByRole("textbox", { name: /^Ärende/ })).toBeNull();
    expect(api.stub.calls.filter((call) => call.method === "POST")).toEqual([]);
    await expectNoAxeViolations(document.body);

    fireEvent.click(button(dialog, messages.flow_runs_start_submit));

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

  it("fills the form from the caller's last run when asked, and the files are picked again", async () => {
    api.routes[LIST] = () => ({
      body: {
        count: 1,
        items: [makeRunSummary({ id: "run-7" })],
        has_more: true,
        status_counts: null
      }
    });
    api.routes[DETAIL] = () => ({
      body: makeRunDetail({ id: "run-7", input_payload_json: { arende: "Bygglov", prio: "Hög" } })
    });
    const { dialog } = await openDialog();
    const reuse = await within(dialog).findByRole("button", {
      name: messages.flow_run_more_reuse
    });
    expect(within(dialog).getByText(messages.flow_run_more_reuse_files)).toBeTruthy();
    const list = api.stub.calls.find((call) => `${call.method} ${call.path}` === LIST);
    expect((list?.init as { params?: { query?: unknown } }).params?.query).toEqual({
      limit: 1,
      mine: true,
      include_status_counts: false
    });
    // The run's input is a content read, made only when asked for.
    expect(api.stub.calls.some((call) => `${call.method} ${call.path}` === DETAIL)).toBe(false);

    fireEvent.click(reuse);

    await waitFor(() =>
      expect((within(dialog).getByLabelText(/^Ärende/) as HTMLInputElement).value).toBe("Bygglov")
    );
    expect(FakeUpload.sent).toEqual([]);
  });

  it("does not offer the last run's input to a caller who has not run the flow", async () => {
    api.routes[LIST] = () => ({
      body: { count: 0, items: [], has_more: false, status_counts: {} }
    });
    const { dialog } = await openDialog();
    await waitFor(() =>
      expect(api.stub.calls.some((call) => `${call.method} ${call.path}` === LIST)).toBe(true)
    );
    expect(within(dialog).queryByRole("button", { name: messages.flow_run_more_reuse })).toBeNull();
  });

  it("goes back from the summary to the form as it was filled in", async () => {
    const { dialog } = await openDialog(
      makeContract({
        form_fields: [{ name: "arende", label: "Ärende", type: "text", required: false }]
      })
    );
    fireEvent.change(within(dialog).getByLabelText(/^Ärende/), { target: { value: "Bygglov" } });
    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
    const summary = within(dialog).getByRole("region", { name: messages.flow_runs_summary_title });
    expect(within(summary).getByText("Bygglov")).toBeTruthy();

    fireEvent.click(button(dialog, messages.back));

    const field = within(dialog).getByLabelText(/^Ärende/) as HTMLInputElement;
    expect(field.value).toBe("Bygglov");
    expect(
      within(dialog).queryByRole("heading", { name: messages.flow_runs_summary_title })
    ).toBeNull();
    // Focus goes to the form's first control, the run's name.
    expect(document.activeElement).toBe(
      within(dialog).getByRole("textbox", {
        name: new RegExp(`^${messages.flow_run_extras_run_label}`)
      })
    );
    expect(button(dialog, messages.cancel)).toBeTruthy();
  });

  it("asks before closing a form with something filled in, and closes an empty one", async () => {
    const { dialog } = await openDialog();
    fireEvent.change(within(dialog).getByLabelText(/^Ärende/), { target: { value: "Bygglov" } });
    fireEvent.click(button(dialog, messages.cancel));

    const confirm = await screen.findByRole("alertdialog", {
      name: messages.flow_run_dialog_close_confirm_title
    });
    fireEvent.click(
      within(confirm).getByRole("button", { name: messages.flow_run_dialog_close_confirm_keep })
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("alertdialog", { name: messages.flow_run_dialog_close_confirm_title })
      ).toBeNull()
    );
    expect((within(dialog).getByLabelText(/^Ärende/) as HTMLInputElement).value).toBe("Bygglov");

    fireEvent.click(button(dialog, messages.cancel));
    fireEvent.click(
      within(
        await screen.findByRole("alertdialog", {
          name: messages.flow_run_dialog_close_confirm_title
        })
      ).getByRole("button", { name: messages.flow_run_dialog_close_confirm_discard })
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Kör Medborgarbrev" })).toBeNull()
    );

    // Opened again, empty: nothing to lose, nothing to ask.
    fireEvent.click(screen.getByRole("button", { name: "Kör" }));
    const again = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    await within(again).findByLabelText(/^Ärende/);
    fireEvent.click(button(again, messages.cancel));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Kör Medborgarbrev" })).toBeNull()
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("says before starting that a sensitive flow limits who may see its material", async () => {
    const { dialog } = await openDialog(contract, {
      care_data_policy: { sensitive: true, pre_approval_visibility: "uploader_and_reviewers" }
    });
    const notice = within(dialog).getByText(messages.flow_runs_sensitive_title);
    expect(within(dialog).getByText(messages.flow_runs_sensitive_body)).toBeTruthy();
    // A lasting state, not news: no live region reads it out again.
    expect(notice.closest("[role=alert]")).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("does not mark a flow sensitive when its policy lets space members see the material", async () => {
    const { dialog } = await openDialog(contract, {
      care_data_policy: { sensitive: true, pre_approval_visibility: "space_members" }
    });
    expect(within(dialog).queryByText(messages.flow_runs_sensitive_title)).toBeNull();
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
    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
    fireEvent.click(button(dialog, messages.flow_runs_start_submit));

    // The form comes back with the refusal at the field.
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
    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
    expect(await within(dialog).findByText(messages.flow_runs_blocked)).toBeTruthy();
    expect(api.stub.calls.filter((call) => call.method === "POST")).toEqual([]);
  });
});
