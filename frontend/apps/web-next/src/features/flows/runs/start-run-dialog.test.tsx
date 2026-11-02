// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { focusManager } from "@tanstack/react-query";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initializeBrowserSession, SESSION_GENERATION_HEADER } from "@/lib/api/refusal";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { makeFlow } from "../flow-fixtures";
import { makeContract, makeInput, makeRunDetail, makeRunSummary } from "./run-fixtures";
import { runKeys, type RunContract, type RunPublic } from "./runs-api";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub: makeStub } = await import("../editor/testing/fixtures");
  api.stub = makeStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

// The core's upload timeout policy as it is; a test can say one of its timeouts ran out.
const timeouts = vi.hoisted(() => ({
  fire: null as null | ((event: { reason: string; timeoutMs: number }) => void)
}));
vi.mock("@eneo/eneo-js/flows/runtime-upload-policy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@eneo/eneo-js/flows/runtime-upload-policy")>();
  return {
    ...actual,
    createFlowRuntimeUploadTimeoutController: (
      params: Parameters<typeof actual.createFlowRuntimeUploadTimeoutController>[0]
    ) => {
      timeouts.fire = params.onTimeout as typeof timeouts.fire;
      return actual.createFlowRuntimeUploadTimeoutController(params);
    }
  };
});

import { StartRunDialog } from "./start-run-dialog";

const CONTRACT = "GET /api/v1/flows/{id}/run-contract/";
const START = "POST /api/v1/flows/{id}/runs/";
const LIST = "GET /api/v1/flows/{id}/runs/";
const DETAIL = "GET /api/v1/flows/{id}/runs/{run_id}/";

/** Answers runtime uploads as the core does, at once. */
class FakeUpload {
  static sent: { url: string; body: FormData }[] = [];
  /** Holds every upload unanswered, as a connection that has stopped. */
  static hold = false;
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
    return `${SESSION_GENERATION_HEADER}: session-a\r\n`;
  }
  abort() {}
  send(body: FormData) {
    FakeUpload.sent.push({ url: this.url, body });
    if (FakeUpload.hold) return;
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
  const { queryClient } = renderInApp(<Harness onStarted={onStarted} metadata={metadata} />);
  fireEvent.click(screen.getByRole("button", { name: "Kör" }));
  const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
  await within(dialog).findByLabelText(/^Ärende/);
  return { dialog, onStarted, queryClient };
}

function button(dialog: HTMLElement, name: string) {
  return within(dialog).getByRole("button", { name });
}

function pickFile(dialog: HTMLElement, file: File) {
  const input = dialog.querySelector<HTMLInputElement>("input[type=file]");
  if (!input) throw new Error("No file input");
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(null, { status: 204, headers: { [SESSION_GENERATION_HEADER]: "session-a" } })
      )
  );
  await initializeBrowserSession();
  api.routes = {};
  FakeUpload.sent = [];
  FakeUpload.hold = false;
  timeouts.fire = null;
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
    expect(FakeUpload.sent[0]?.url).toBe("/api/v1/flows/flow-1/steps/step-1/runtime-files/");

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

  it("downloads a file already uploaded to the form through a link signed for its owner", async () => {
    api.routes["POST /api/v1/files/{id}/signed-url/"] = () => ({
      body: { url: "http://backend:8000/api/v1/files/file-1/download/?token=signed", expires_at: 0 }
    });
    const saved: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement
    ) {
      saved.push(`${this.getAttribute("href")} ${this.download}`);
    });
    const { dialog } = await openDialog();
    pickFile(dialog, new File(["%PDF"], "brev.pdf", { type: "application/pdf" }));
    expect(await within(dialog).findByText(/Uppladdad/)).toBeTruthy();

    fireEvent.click(button(dialog, "Ladda ned brev.pdf"));
    await waitFor(() =>
      expect(saved).toEqual(["/api/v1/files/file-1/download/?token=signed brev.pdf"])
    );
    expect(
      api.stub.calls.find((call) => call.path === "/api/v1/files/{id}/signed-url/")?.init
    ).toMatchObject({
      params: { path: { id: "file-1" } },
      body: { content_disposition: "attachment" }
    });
    click.mockRestore();
  });

  it.each([
    [
      "not_started",
      "Uppladdningen startade inte inom 30 s. Kontrollera anslutningen och försök igen."
    ],
    ["server_not_responding", "Filen skickades, men servern svarade inte inom 30 s. Försök igen."],
    ["stalled", "Uppladdningen stod stilla i 30 s. Kontrollera anslutningen och försök igen."]
  ])("says which upload timeout ran out: %s", async (reason, text) => {
    FakeUpload.hold = true;
    const { dialog } = await openDialog();
    pickFile(dialog, new File(["%PDF"], "brev.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(timeouts.fire).not.toBeNull());
    act(() => timeouts.fire?.({ reason, timeoutMs: 30_000 }));

    expect(await within(dialog).findByText(text)).toBeTruthy();
    // A screen reader hears why, not only that it failed.
    await waitFor(() =>
      expect(document.querySelector('[data-astryx-live-region="polite"]')?.textContent).toContain(
        `${messages.flow_runs_upload_failed.replace("{name}", "brev.pdf")} ${text}`
      )
    );
    // It may pass: the file can be sent again.
    expect(
      button(dialog, messages.flow_transcript_upload_retry.replace("{name}", "brev.pdf"))
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

  it("keeps the form and what was filled in when the contract cannot be read again", async () => {
    const { dialog, queryClient } = await openDialog();
    fireEvent.change(within(dialog).getByLabelText(/^Ärende/), { target: { value: "Bygglov" } });

    api.routes[CONTRACT] = () => ({ status: 503, body: { message: "Busy" } });
    await act(() => queryClient.invalidateQueries({ queryKey: runKeys.contract("flow-1") }));

    expect(await within(dialog).findByText(messages.query_error_refresh_title)).toBeTruthy();
    expect((within(dialog).getByLabelText(/^Ärende/) as HTMLInputElement).value).toBe("Bygglov");
    expect(within(dialog).queryByText(messages.flow_runs_contract_failed)).toBeNull();
  });

  it("reads the contract once per opening, not again when the person comes back to the tab", async () => {
    await openDialog();
    const reads = () => api.stub.calls.filter((call) => `${call.method} ${call.path}` === CONTRACT);
    expect(reads()).toHaveLength(1);

    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    focusManager.setFocused(undefined);
    await act(async () => {});
    expect(reads()).toHaveLength(1);
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

describe("StartRunDialog on a phone", () => {
  it("takes the whole screen, stacks the footer with the primary action first and has nothing to drag", async () => {
    const standard = (await openDialog()).dialog.className;
    cleanup();

    setViewport("phone");
    const { dialog } = await openDialog();
    // The fullscreen variant is another set of the dialog's own classes.
    expect(dialog.className).not.toBe(standard);
    const next = button(dialog, "Granska");
    const cancel = button(dialog, "Avbryt");
    expect(next.parentElement).toBe(cancel.parentElement);
    // The primary action is on top, and first in the DOM, so Tab goes the way the eye does.
    expect(next.parentElement?.className).toContain("flex-col");
    expect(next.parentElement?.className).not.toContain("flex-col-reverse");
    expect(Boolean(next.compareDocumentPosition(cancel) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(
      true
    );
    expect(within(dialog).getByText("Välj filer")).toBeTruthy();
    expect(within(dialog).queryByText(/dra hit/)).toBeNull();
  });

  describe("an audio step", () => {
    const audio = {
      ...contract,
      steps_requiring_input: [
        makeInput({
          label: "Ljud",
          input_format: "audio",
          accepted_mimetypes: ["audio/wav"]
        })
      ]
    };
    /** Whether `first` comes before `second` in the document. */
    const before = (first: Element, second: Element) =>
      Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
    const pieces = (dialog: HTMLElement) => ({
      recording: within(dialog).getByText(messages.flow_transcript_rec_heading),
      file: dialog.querySelector<HTMLInputElement>("input[type=file]")!,
      name: within(dialog).getByLabelText(/^Namn på körningen/)
    });

    it("puts recording first and the run's name last on a phone", async () => {
      setViewport("phone");
      const { dialog } = await openDialog(audio);
      const { recording, file, name } = pieces(dialog);
      expect(before(recording, file)).toBe(true);
      expect(before(file, name)).toBe(true);
    });

    it("keeps recording first when the phone is held sideways", async () => {
      setViewport({ width: 844, height: 390, pointer: "coarse" });
      const { dialog } = await openDialog(audio);
      const { recording, file, name } = pieces(dialog);
      expect(before(recording, file)).toBe(true);
      expect(before(file, name)).toBe(true);
    });

    it("names the step's recording and file together, for a screen reader", async () => {
      const { dialog } = await openDialog(audio);
      const group = within(dialog).getByRole("group", { name: /^Ljud/ });
      const { recording, file } = pieces(dialog);
      expect(group.contains(recording)).toBe(true);
      expect(group.contains(file)).toBe(true);
    });

    it("keeps the run's name first and the file above the recording for a mouse", async () => {
      const { dialog } = await openDialog(audio);
      const { recording, file, name } = pieces(dialog);
      expect(before(name, file)).toBe(true);
      expect(before(file, recording)).toBe(true);
    });

    it("keeps the file above the recording on a narrow window with a mouse", async () => {
      setViewport({ width: 600, height: 800, pointer: "fine" });
      const { dialog } = await openDialog(audio);
      const { recording, file, name } = pieces(dialog);
      expect(before(name, file)).toBe(true);
      expect(before(file, recording)).toBe(true);
    });
  });

  it("keeps the whole screen when the phone is held sideways, where it is as short as ever", async () => {
    const standard = (await openDialog()).dialog.className;
    cleanup();

    setViewport({ width: 844, height: 390, pointer: "coarse" });
    const { dialog } = await openDialog();
    expect(dialog.className).not.toBe(standard);
    cleanup();

    // A tablet held upright is tall: its dialog stays the centred one.
    setViewport("tablet-portrait");
    expect((await openDialog()).dialog.className).toBe(standard);
  });

  it("keeps the dialog, its row of buttons and the drag wording for a mouse", async () => {
    const { dialog } = await openDialog();
    const next = button(dialog, "Granska");
    const cancel = button(dialog, "Avbryt");
    expect(next.parentElement?.className).toContain("justify-end");
    expect(next.parentElement?.className).not.toContain("flex-col");
    // A row reads left to right: Avbryt, then Granska, in Tab order too.
    expect(Boolean(cancel.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(
      true
    );
    expect(within(dialog).getByText("Välj filer eller dra hit dem")).toBeTruthy();
  });
});
