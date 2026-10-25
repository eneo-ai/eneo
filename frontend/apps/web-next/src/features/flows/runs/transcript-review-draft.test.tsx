// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { ReviewPanel } from "./review-panel";
import { makeCheckpoint } from "./run-fixtures";
import { RunTranscripts } from "./run-transcript";
import { runKeys, transcriptRevisionsQueryOptions } from "./runs-api";
import { parseSegments, shownSegments, type TranscriptTarget } from "./transcript";

const state = vi.hoisted(() => ({
  announce: vi.fn(),
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));
vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("../editor/testing/fixtures");
  state.stub = apiStub(new Proxy({}, { get: (_target, key: string) => state.routes[key] }));
  return { browserApi: state.stub.client };
});
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace: space } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => space({})) };
});
// Counted, to tell whether a render with the same data reads the lines again.
vi.mock("./transcript", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./transcript")>();
  return {
    ...actual,
    parseSegments: vi.fn(actual.parseSegments),
    shownSegments: vi.fn(actual.shownSegments)
  };
});
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));

const SOURCE =
  "GET /api/v1/flows/{flow_id}/runs/{run_id}/steps/{step_id}/attempts/{attempt_no}/transcript-source/";
const CORRECTIONS = "GET /api/v1/flows/{id}/runs/{run_id}/transcript-corrections/";
const EDIT = "PATCH /api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-corrections/";
const APPROVE =
  "POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/";

const target: TranscriptTarget = { stepId: "step-1", stepOrder: 1, attemptNo: 1, fileIds: [] };

/** The core's answer to a save: the set as sent, at the next revision. */
function saved(body: Record<string, unknown>, revision: number) {
  return {
    flow_run_id: "run-1",
    step_id: "step-1",
    created_at: "2026-10-22T09:00:00Z",
    updated_at: "2026-10-22T09:00:00Z",
    edited_by_principal_type: "user",
    schema_version: 3,
    segments_hash: "hash-1",
    stale: false,
    revision,
    occurrences: body.occurrences,
    speaker_edits: body.speaker_edits,
    speaker_names: body.speaker_names ?? {}
  };
}

function answer({ failSaves = 0 } = {}) {
  let failures = failSaves;
  let revision = 0;
  state.routes[SOURCE] = () => ({
    body: {
      status: "present",
      run_id: "run-1",
      step_id: "step-1",
      attempt_no: 1,
      source_hash: "hash-1",
      bounds: { segments_bytes: 1, detail_bytes: 0, words_bytes: 0, segments_count: 2 },
      component_omissions: {},
      start_segment_index: 0,
      page_size: 200,
      max_response_bytes: 1000000,
      next_segment_index: null,
      segments: [
        {
          segment_index: 0,
          file_index: 0,
          start: 0,
          end: 3,
          speaker: "SPEAKER_00",
          text: "Välkomna."
        },
        {
          segment_index: 1,
          file_index: 0,
          start: 65,
          end: 70,
          speaker: "SPEAKER_01",
          text: "Tack."
        }
      ]
    }
  });
  state.routes[CORRECTIONS] = () => ({ body: [] });
  state.routes[EDIT] = (init: { body: Record<string, unknown> }) => {
    if (failures > 0) {
      failures -= 1;
      return { status: 503, body: { message: "Busy", code: "service_unavailable" } };
    }
    revision += 1;
    return { body: saved(init.body, revision) };
  };
  state.routes[APPROVE] = () => ({
    body: { checkpoint: makeCheckpoint({ state: "resumed" }), run: { id: "run-1" } }
  });
}

function calls(route: string) {
  return state.stub.calls.filter((call) => `${call.method} ${call.path}` === route);
}

async function renderReview() {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], makeSpace({}));
  const view = renderInApp(
    <ReviewPanel
      checkpoint={makeCheckpoint({
        step_id: "step-1",
        step_order: 1,
        step_label: "Transkribera",
        current_payload_json: { text: "Välkomna. Tack." },
        original_payload_json: { text: "Välkomna. Tack." }
      })}
      mayReview
      now={Date.parse("2026-10-22T09:00:00Z")}
      onStale={() => undefined}
      transcript={target}
    />,
    { queryClient }
  );
  const panel = await screen.findByRole("region", { name: "Granska steg 1: Transkribera" });
  const lines = await within(panel).findByRole("list", {
    name: messages.flow_runs_transcript_lines
  });
  return { panel, lines, ...view };
}

/** Corrects the second line through its editor. */
function correctLine(lines: HTMLElement, text: string) {
  fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 1:05" }));
  fireEvent.change(within(lines).getByLabelText("Texten på raden 1:05"), {
    target: { value: text }
  });
  fireEvent.click(within(lines).getByRole("button", { name: messages.flow_transcript_line_save }));
}

beforeEach(() => {
  state.routes = {};
});

afterEach(() => {
  cleanup();
  state.stub.calls.length = 0;
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("The review's transcript draft", () => {
  it("shows a correction at once and approves only after the draft is saved", async () => {
    answer();
    const { panel, lines } = await renderReview();
    correctLine(lines, "Tackar.");
    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_line_saved)
    );
    // The line shows corrected before the save; approving sends the draft first.
    expect(lines.textContent).toContain("Tackar.");
    expect(within(panel).getByText(messages.flow_transcript_draft_saving)).toBeTruthy();
    expect(calls(EDIT)).toHaveLength(0);
    fireEvent.click(within(panel).getByRole("button", { name: messages.flow_runs_review_approve }));
    await waitFor(() => expect(calls(APPROVE)).toHaveLength(1));
    expect(calls(EDIT)).toHaveLength(1);
    expect(calls(EDIT)[0]!.init.body).toMatchObject({
      expected_revision: null,
      occurrences: [
        { segment_index: 1, char_start: 4, char_end: 5, original: ".", corrected: "ar." }
      ]
    });
    expect(state.stub.calls.indexOf(calls(EDIT)[0]!)).toBeLessThan(
      state.stub.calls.indexOf(calls(APPROVE)[0]!)
    );
  });

  it("keeps the draft when a save fails, holds approval, and saves it again or as a file", async () => {
    answer({ failSaves: 1 });
    const made: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      made.push(blob as Blob);
      return "blob:draft";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const { panel, lines, container } = await renderReview();
    correctLine(lines, "Tackar.");

    // The draft saves itself a moment later; the core is busy.
    expect(
      await within(panel).findByText(
        messages.flow_transcript_draft_failed_title,
        {},
        { timeout: 3_000 }
      )
    ).toBeTruthy();
    expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_draft_failed_title);
    expect(lines.textContent).toContain("Tackar.");
    await expectNoAxeViolations(container);

    // Approval is held, and focus goes to saving again.
    fireEvent.click(within(panel).getByRole("button", { name: messages.flow_runs_review_approve }));
    expect(
      await within(panel).findByText(messages.flow_transcript_review_draft_unsaved)
    ).toBeTruthy();
    const retry = within(panel).getByRole("button", { name: messages.flow_transcript_draft_retry });
    expect(document.activeElement).toBe(retry);
    expect(calls(APPROVE)).toHaveLength(0);

    // The draft as a file: the request that was not accepted, with where it belongs.
    fireEvent.click(
      within(panel).getByRole("button", { name: messages.flow_transcript_draft_download })
    );
    expect(click).toHaveBeenCalled();
    const file = JSON.parse(
      await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.readAsText(made[0]!);
      })
    );
    expect(file).toMatchObject({
      flow_id: "flow-1",
      run_id: "run-1",
      step_id: "step-1",
      expected_revision: null,
      occurrences: [{ segment_index: 1, corrected: "ar." }]
    });

    await act(async () => {
      fireEvent.click(retry);
    });
    await waitFor(() => expect(calls(EDIT)).toHaveLength(2));
    await waitFor(() =>
      expect(within(panel).queryByText(messages.flow_transcript_draft_failed_title)).toBeNull()
    );
    fireEvent.click(within(panel).getByRole("button", { name: messages.flow_runs_review_approve }));
    await waitFor(() => expect(calls(APPROVE)).toHaveLength(1));
  });

  it("has the step's correction history read again once the draft is saved", async () => {
    answer();
    const { lines, queryClient } = await renderReview();
    const history = transcriptRevisionsQueryOptions("flow-1", "run-1", "step-1").queryKey;
    queryClient.setQueryData(history, { pages: [], pageParams: [] });
    correctLine(lines, "Tackar.");

    await waitFor(() => expect(calls(EDIT)).toHaveLength(1), { timeout: 3_000 });
    await waitFor(() => expect(queryClient.getQueryState(history)?.isInvalidated).toBe(true));
  });

  it("has the step's correction history read again when someone else saved first", async () => {
    answer();
    state.routes[EDIT] = () => ({
      status: 400,
      body: { message: "Stale", code: "flow_transcript_corrections_stale_revision" }
    });
    const { lines, queryClient } = await renderReview();
    const history = transcriptRevisionsQueryOptions("flow-1", "run-1", "step-1").queryKey;
    queryClient.setQueryData(history, { pages: [], pageParams: [] });
    correctLine(lines, "Tackar.");

    await waitFor(() => expect(calls(EDIT)).toHaveLength(1), { timeout: 3_000 });
    await waitFor(() => expect(queryClient.getQueryState(history)?.isInvalidated).toBe(true));
  });
});

describe("A run's transcript", () => {
  it("reads the lines once while the data holds and again when the corrections change", async () => {
    answer();
    const queryClient = testQueryClient();
    queryClient.setQueryData(["spaces", "space-1"], makeSpace({}));
    const page = (label: string) => (
      <RunTranscripts
        flowId="flow-1"
        runId="run-1"
        targets={[target]}
        labelFor={() => label}
        mayEdit={false}
        runCompleted
      />
    );
    const { rerender } = renderInApp(page("Transkribera"), { queryClient });
    const lines = await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
    expect(lines.textContent).toContain("Tack.");

    // The page renders again (a poll, Refresh) with the same transcript and corrections.
    vi.mocked(parseSegments).mockClear();
    vi.mocked(shownSegments).mockClear();
    rerender(page("Transkribering"));
    expect(screen.getByRole("heading", { name: "Transkribering" })).toBeTruthy();
    expect(parseSegments).not.toHaveBeenCalled();
    expect(shownSegments).not.toHaveBeenCalled();

    // A saved correction still shows.
    act(() =>
      queryClient.setQueryData(runKeys.corrections("flow-1", "run-1"), [
        saved(
          {
            occurrences: [
              {
                segment_index: 1,
                char_start: 0,
                char_end: 4,
                original: "Tack",
                corrected: "Tackar"
              }
            ],
            speaker_edits: []
          },
          1
        )
      ])
    );
    await waitFor(() => expect(lines.textContent).toContain("Tackar."));
    expect(parseSegments).not.toHaveBeenCalled();
    expect(shownSegments).toHaveBeenCalled();
  });
});
