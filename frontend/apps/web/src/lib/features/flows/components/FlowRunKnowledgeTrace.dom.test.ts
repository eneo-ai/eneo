import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import type { Eneo, FlowRunDebugRag } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

import FlowRunKnowledgeTrace from "./FlowRunKnowledgeTrace.svelte";

afterEach(() => {
  cleanup();
});

// The trace renders no source rows for these cases, so the client is never
// called; a bare object keeps the test about the status line it is checking.
const eneo = {} as Eneo;

function renderTrace(status: string) {
  return render(FlowRunKnowledgeTrace, {
    rag: { status, chunks_retrieved: 0 } as unknown as FlowRunDebugRag,
    eneo,
    stepOrder: 1
  });
}

describe("FlowRunKnowledgeTrace status line", () => {
  // The runtime is not bounded by RagRetrievalStatus: the provenance model
  // accepts any extra field, and the speaker-mapping handler records a bare
  // "skipped". Every value a handler actually writes needs a sentence here,
  // or the run evidence shows a municipal user the identifier itself.
  it.each([
    ["success", () => m.flow_run_knowledge_status_success()],
    ["timeout", () => m.flow_run_knowledge_status_timeout()],
    ["error", () => m.flow_run_knowledge_status_error()],
    ["no_chunks", () => m.flow_run_knowledge_status_no_chunks()],
    ["skipped", () => m.flow_run_knowledge_status_skipped()],
    ["skipped_no_input", () => m.flow_run_knowledge_status_skipped_no_input()],
    ["skipped_no_service", () => m.flow_run_knowledge_status_skipped_no_service()],
    ["skipped_no_knowledge", () => m.flow_run_knowledge_status_skipped_no_knowledge()],
    ["skipped_transcribe_only", () => m.flow_run_knowledge_status_skipped_transcribe_only()]
  ])("reads %s as a sentence", (status, expected) => {
    renderTrace(status);
    expect(screen.getByText(expected())).toBeTruthy();
  });

  it("never shows the raw identifier for a status it does not know", () => {
    renderTrace("some_future_runtime_status");
    expect(screen.getByText(m.unknown())).toBeTruthy();
    expect(screen.queryByText("some_future_runtime_status")).toBeNull();
  });
});
