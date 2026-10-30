// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeFlow } from "../flow-fixtures";
import { makeContract, makeInput, makeRunSummary } from "./run-fixtures";
import type { RunContract } from "./runs-api";

const state = vi.hoisted(() => ({
  seconds: null as number | null,
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("../editor/testing/fixtures");
  state.stub = apiStub(new Proxy({}, { get: (_target, key: string) => state.routes[key] }));
  return { browserApi: state.stub.client };
});
// jsdom reads no media metadata; the browser's measurement is stood in for.
vi.mock("./audio-length", () => ({ measureAudioSeconds: () => Promise.resolve(state.seconds) }));

import { StartRunDialog } from "./start-run-dialog";

const CONTRACT = "GET /api/v1/flows/{id}/run-contract/";
const START = "POST /api/v1/flows/{id}/runs/";

async function openDialog(contract: RunContract) {
  state.routes[CONTRACT] = () => ({ body: contract });
  const onStarted = vi.fn();
  renderInApp(
    <StartRunDialog
      flow={makeFlow({ published_version: 4 })}
      open
      onOpenChange={() => undefined}
      onStarted={onStarted}
    />
  );
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByLabelText(new RegExp(`^${messages.flow_run_extras_run_label}`));
  return { dialog, onStarted };
}

beforeEach(() => {
  state.routes = {};
  state.seconds = null;
});

afterEach(() => {
  cleanup();
  state.stub.calls.length = 0;
});

describe("StartRunDialog extras", () => {
  it("starts the run under the name given, trimmed", async () => {
    const run = makeRunSummary({ id: "run-9", status: "queued" });
    state.routes[START] = () => ({ status: 201, body: run });
    const { dialog, onStarted } = await openDialog(makeContract({ published_flow_version: 4 }));

    fireEvent.change(
      within(dialog).getByLabelText(new RegExp(`^${messages.flow_run_extras_run_label}`)),
      { target: { value: "  Ärende 2026-114 " } }
    );
    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_summary_next }));
    expect(within(dialog).getByText("Ärende 2026-114")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_start_submit }));

    await waitFor(() => expect(onStarted).toHaveBeenCalledWith(run));
    const call = state.stub.calls.find((entry) => `${entry.method} ${entry.path}` === START);
    expect(call?.init.body).toMatchObject({
      expected_flow_version: 4,
      run_label: "Ärende 2026-114"
    });
  });

  it("shows each template the flow fills and whether it is ready", async () => {
    const { dialog } = await openDialog(
      makeContract({
        template_readiness: [
          { step_id: "step-1", template_name: "Beslutsmall", status: "ready" },
          {
            step_id: "step-2",
            template_name: "Brevmall",
            status: "needs_action",
            message_code: "flow_template_no_controls"
          }
        ]
      })
    );
    const templates = within(dialog).getByRole("region", {
      name: messages.flow_run_extras_templates_heading
    });
    const rows = within(templates).getAllByRole("listitem");
    expect(within(rows[0]!).getByText(messages.flow_run_extras_template_ready)).toBeTruthy();
    expect(within(rows[1]!).getByText(messages.flow_run_extras_template_needs_action)).toBeTruthy();
    expect(within(rows[1]!).getByText(messages.flow_error_flow_template_no_controls)).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("refuses audio longer than one file of the step can hold, before uploading it", async () => {
    state.seconds = 5400;
    const { dialog } = await openDialog(
      makeContract({
        steps_requiring_input: [
          makeInput({
            label: "Inspelning",
            input_format: "audio",
            accepted_mimetypes: ["audio/mpeg"],
            max_duration_seconds: 3600
          })
        ]
      })
    );
    const upload = vi.fn();
    vi.stubGlobal("XMLHttpRequest", upload);
    const input = dialog.querySelector<HTMLInputElement>("input[type=file]")!;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "mote.mp3", { type: "audio/mpeg" })] }
    });

    expect(
      await within(dialog).findByText(
        "mote.mp3 är 90 min 0 s lång. Steget kan transkribera högst 60 min 0 s per fil. Dela upp ljudet eller välj en kortare fil."
      )
    ).toBeTruthy();
    expect(upload).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
