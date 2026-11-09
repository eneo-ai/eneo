// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { runKeys } from "./runs-api";
import type { TranscriptTarget } from "./transcript";

const state = vi.hoisted(() => ({
  /** Whether the page's navigation currently asks before leaving. */
  guarded: false,
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("../editor/testing/fixtures");
  state.stub = apiStub(new Proxy({}, { get: (_target, key: string) => state.routes[key] }));
  return { browserApi: state.stub.client };
});
vi.mock("@/lib/navigation", async () => ({
  ...(await import("@/test/navigation")),
  useLeaveConfirmation: (active: boolean) => {
    state.guarded = active;
    return { blocked: false, leave() {}, stay() {} };
  }
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace: space } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => space({})) };
});

import { RunTranscript, TranscriptSlot } from "./run-transcript";

const SOURCE =
  "GET /api/v1/flows/{flow_id}/runs/{run_id}/steps/{step_id}/attempts/{attempt_no}/transcript-source/";
const CORRECTIONS = "GET /api/v1/flows/{id}/runs/{run_id}/transcript-corrections/";
const TARGET: TranscriptTarget = {
  stepId: "step-1",
  stepOrder: 1,
  attemptNo: 1,
  fileIds: ["audio-1"]
};
const STEP_TEXT = "Vad steget skrev";
const refused = () => ({ status: 503, body: { message: "Unavailable", code: "unavailable" } });

function answerTranscript() {
  state.routes[CORRECTIONS] = () => ({ body: [] });
  state.routes[SOURCE] = () => ({
    body: {
      status: "present",
      run_id: "run-1",
      step_id: "step-1",
      attempt_no: 1,
      source_hash: "hash-1",
      bounds: { segments_bytes: 1, detail_bytes: 0, words_bytes: 0, segments_count: 1 },
      component_omissions: {},
      start_segment_index: 0,
      page_size: 200,
      max_response_bytes: 1000000,
      next_segment_index: null,
      segments: [
        {
          segment_index: 0,
          file_index: 0,
          start: 65,
          end: 70,
          speaker: "SPEAKER_01",
          text: "Tack."
        }
      ]
    }
  });
}

function renderTranscript(proposedNames?: Record<string, string>) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], makeSpace({}));
  return renderInApp(
    <RunTranscript
      flowId="flow-1"
      runId="run-1"
      target={TARGET}
      mayEdit
      runCompleted
      proposedNames={proposedNames}
      fallback={<p>{STEP_TEXT}</p>}
    />,
    { queryClient, appContext: testAppContext({ permissions: ["flows_view", "flows_manage"] }) }
  );
}

async function editLine() {
  const lines = await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
  fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 1:05" }));
  fireEvent.change(screen.getByLabelText("Texten på raden 1:05"), {
    target: { value: "Tack så mycket." }
  });
}

beforeEach(() => {
  state.routes = {};
  state.guarded = false;
  answerTranscript();
});

afterEach(() => {
  cleanup();
  state.stub.calls.length = 0;
});

describe("RunTranscript", () => {
  it.each([
    ["transcript", SOURCE],
    ["corrections", CORRECTIONS]
  ])("keeps the step's text under the reason when its %s cannot be read", async (_, route) => {
    state.routes[route] = refused;
    renderTranscript();

    expect(await screen.findByText(messages.flow_runs_transcript_failed)).toBeTruthy();
    expect(screen.getByText(STEP_TEXT)).toBeTruthy();
  });

  it("keeps the lines and an edit not saved yet when reading them again fails, and says so once", async () => {
    const { queryClient } = renderTranscript();
    await editLine();

    state.routes[CORRECTIONS] = refused;
    state.routes[SOURCE] = refused;
    await act(() =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: runKeys.run("flow-1", "run-1") }),
        queryClient.invalidateQueries({ queryKey: runKeys.transcripts("flow-1", "run-1") })
      ])
    );

    expect(screen.getAllByText(messages.query_error_refresh_title)).toHaveLength(1);
    expect(screen.getByLabelText<HTMLTextAreaElement>("Texten på raden 1:05").value).toBe(
      "Tack så mycket."
    );
    expect(screen.queryByText(messages.flow_runs_transcript_failed)).toBeNull();
    expect(screen.queryByText(STEP_TEXT)).toBeNull();
  });

  it("names the speakers as the run's speaker-mapping step did until someone names them here", async () => {
    renderTranscript({ SPEAKER_01: "Erik" });

    const lines = await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
    expect(within(lines).getByText("Erik")).toBeTruthy();
    expect(within(lines).queryByText("Talare 2")).toBeNull();
    const field = screen.getByLabelText<HTMLInputElement>("Namn för Talare 2");
    expect(field.value).toBe("Erik");

    // The step's name is no change to save; a name given here is.
    fireEvent.submit(field.closest("form")!);
    expect(state.stub.calls.filter((call) => call.method === "PUT")).toHaveLength(0);
  });

  it("shows a name given here over the step's, and a name cleared here as none", async () => {
    state.routes[CORRECTIONS] = () => ({
      body: [
        {
          step_id: "step-1",
          revision: 2,
          segments_hash: "hash-1",
          schema_version: 3,
          stale: false,
          occurrences: [],
          speaker_edits: [],
          speaker_names: { SPEAKER_01: "Erik Svensson", SPEAKER_02: null }
        }
      ]
    });
    renderTranscript({ SPEAKER_01: "Erik", SPEAKER_02: "Anna" });

    const lines = await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
    expect(within(lines).getByText("Erik Svensson")).toBeTruthy();
    expect(screen.getByLabelText<HTMLInputElement>("Namn för Talare 2").value).toBe(
      "Erik Svensson"
    );
  });

  it("asks before the app's own links leave a correction not saved yet", async () => {
    renderTranscript();
    await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
    expect(state.guarded).toBe(false);

    await editLine();
    expect(state.guarded).toBe(true);
  });
});

describe("TranscriptSlot", () => {
  /** A host with a control in it, as a transcript being worked in. */
  function hostWithControl() {
    const host = document.createElement("div");
    const control = host.appendChild(document.createElement("button"));
    return { host, control };
  }

  it("keeps focus in the transcript when its element moves to another slot", () => {
    const { host, control } = hostWithControl();
    const page = (wide: boolean) =>
      wide ? (
        <section>
          <TranscriptSlot host={host} isOpen />
        </section>
      ) : (
        <article>
          <TranscriptSlot host={host} isOpen />
        </article>
      );
    const { rerender } = renderInApp(page(true));
    control.focus();
    expect(document.activeElement).toBe(control);

    rerender(page(false));
    expect(host.closest("article")).not.toBeNull();
    expect(document.activeElement).toBe(control);
  });

  it("leaves focus where it is when a folded transcript comes back later", async () => {
    const { host, control } = hostWithControl();
    const page = (open: boolean) => (open ? <TranscriptSlot host={host} isOpen /> : null);
    const { rerender } = renderInApp(page(true));
    control.focus();

    rerender(page(false));
    await act(async () => {});
    rerender(page(true));
    expect(host.isConnected).toBe(true);
    expect(document.activeElement).not.toBe(control);
  });
});
