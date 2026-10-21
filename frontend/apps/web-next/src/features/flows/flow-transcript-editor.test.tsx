// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Schema } from "@/lib/api/models";
import { FlowRunTranscript, transcriptCorrectionBody } from "./flow-transcript-editor";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const base: Schema<"FlowTranscriptPublic"> = {
  flow_run_id: "run-1",
  step_id: "step-1",
  segments_hash: "a".repeat(64),
  corrections_revision: null,
  corrections: null,
  original_segments: [{ start: 0, end: 5, text: "Hej 🙂", speaker: "SPEAKER_00" }],
  segments: [{ start: 0, end: 5, text: "Hej 🙂", speaker: "SPEAKER_00" }],
  speaker_names: { SPEAKER_00: "Anna" },
  text: "Hej 🙂"
};

it("anchors Unicode corrections to the original transcript and preserves unchanged span edits", () => {
  const corrected = transcriptCorrectionBody(base, ["Hej allihop"], ["SPEAKER_00"], {
    SPEAKER_00: "Anna"
  });
  expect(corrected.occurrences).toEqual([
    { segment_index: 0, char_start: 0, char_end: 5, original: "Hej 🙂", corrected: "Hej allihop" }
  ]);
  expect(corrected.expected_revision).toBeNull();
});

it("edits and saves text and names through the existing correction endpoint", async () => {
  api.GET.mockResolvedValue({ data: base, response: new Response("{}") });
  api.PATCH.mockResolvedValue({ data: { revision: 1 }, response: new Response("{}") });
  const { container } = renderInApp(
    <FlowRunTranscript flowId="flow-1" runId="run-1" stepId="step-1" />
  );
  fireEvent.click(await screen.findByRole("button", { name: "Rätta transkript" }));
  expect(document.activeElement).toBe(screen.getByLabelText("Namn för SPEAKER_00"));
  await expectNoAxeViolations(container);
  fireEvent.change(screen.getByLabelText("Text i avsnitt 1"), { target: { value: "Hej allihop" } });
  fireEvent.change(screen.getByLabelText("Namn för SPEAKER_00"), { target: { value: "Maria" } });
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  const [path, options] = api.PATCH.mock.calls[0]!;
  expect(path).toContain("transcript-corrections");
  expect(options.body.segments_hash).toBe(base.segments_hash);
  expect(options.body.speaker_names).toEqual({ SPEAKER_00: "Maria" });
  expect(options.body.occurrences[0].corrected).toBe("Hej allihop");
});

it("retains an open edit and its revision when query data changes, then explains a conflict", async () => {
  const current = {
    ...base,
    corrections_revision: 4,
    corrections: {
      schema_version: 3,
      flow_run_id: "run-1",
      step_id: "step-1",
      segments_hash: base.segments_hash,
      occurrences: [],
      speaker_edits: [],
      speaker_names: {},
      revision: 4,
      stale: false,
      edited_by_principal_type: "user" as const,
      created_at: "2026-10-21T10:00:00Z",
      updated_at: "2026-10-21T10:00:00Z"
    }
  };
  api.GET.mockResolvedValue({ data: current, response: new Response("{}") });
  api.PATCH.mockResolvedValue({
    error: { message: "Changed", code: "flow_transcript_corrections_stale_revision" },
    response: new Response(null, { status: 400 })
  });
  const { queryClient } = renderInApp(
    <FlowRunTranscript flowId="flow-1" runId="run-1" stepId="step-1" />
  );
  fireEvent.click(await screen.findByRole("button", { name: "Rätta transkript" }));
  fireEvent.change(screen.getByLabelText("Text i avsnitt 1"), {
    target: { value: "My correction" }
  });
  queryClient.setQueryData(["flows", "flow-1", "runs", "run-1", "transcript", "step-1"], {
    ...current,
    corrections_revision: 5
  });
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Din text finns kvar"))
  );
  expect(api.PATCH.mock.calls[0]![1].body.expected_revision).toBe(4);
  expect((screen.getByLabelText("Text i avsnitt 1") as HTMLTextAreaElement).value).toBe(
    "My correction"
  );
});
