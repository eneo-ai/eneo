import { cleanup, render, screen, waitFor } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import type { Eneo, FlowRunDebugRagReference, RetrievedPassage } from "@eneo/eneo-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowChunkViewer from "./FlowChunkViewer.svelte";
import FlowRunKnowledgeSourceRow from "./FlowRunKnowledgeSourceRow.svelte";

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn()
  });
});

// The reviewer-facing count contract: matched=3 (retrieval), recorded=2
// (evidence policy), disclosed=1 (one recorded passage's text withheld).
const PASSAGES: RetrievedPassage[] = [
  {
    chunk_no: 1,
    score: 0.8,
    text: "Synligt textavsnitt ur källan",
    recording: "complete",
    passage_bytes: 28,
    recorded_bytes: 28
  },
  {
    chunk_no: 2,
    score: 0.7,
    text: null,
    disclosure: "text_withheld_sensitive_flow",
    recording: "complete",
    passage_bytes: 12,
    recorded_bytes: 12
  } as unknown as RetrievedPassage
];

function makeEneo(): Eneo {
  return {
    infoBlobs: {
      get: vi.fn().mockResolvedValue({
        text: "Synligt textavsnitt ur källan och resten av dokumentet.",
        metadata: {}
      })
    }
  } as unknown as Eneo;
}

describe("knowledge count presentation", () => {
  it("the source row reports recorded (saved) of matched, never the disclosed count", () => {
    const reference = {
      id: "11111111-1111-1111-1111-111111111111",
      id_short: "11111111",
      best_score: 0.8,
      matched_chunk_count: 3,
      recorded_passage_count: 2,
      passages: PASSAGES
    } as unknown as FlowRunDebugRagReference;

    render(FlowRunKnowledgeSourceRow, {
      reference,
      index: 0,
      eneo: makeEneo()
    });

    expect(
      screen.getByText(
        m.flow_run_knowledge_chunks_displayed_of_matched({ displayed: "2", matched: "3" })
      )
    ).toBeTruthy();
  });

  it("marks the best match when every score is negative", async () => {
    // Cosine similarity can be negative for all passages; a zero sentinel
    // used to leave no passage marked at all.
    const negativePassages: RetrievedPassage[] = [
      {
        chunk_no: 1,
        score: -0.4,
        text: "Första stycket",
        recording: "complete",
        passage_bytes: 14,
        recorded_bytes: 14
      },
      {
        chunk_no: 2,
        score: -0.2,
        text: "Andra stycket",
        recording: "complete",
        passage_bytes: 13,
        recorded_bytes: 13
      }
    ];

    render(FlowChunkViewer, {
      eneo: makeEneo(),
      infoBlobId: "11111111-1111-1111-1111-111111111111",
      title: "Källdokument",
      passages: negativePassages,
      matchedChunkCount: 2,
      children: createRawSnippet((args: () => { showViewer: () => void }) => ({
        render: () => `<button data-testid="open-viewer">open</button>`,
        setup: (element) => {
          element.addEventListener("click", () => args().showViewer());
        }
      }))
    });

    screen.getByTestId("open-viewer").click();

    await waitFor(() => {
      expect(screen.getByText(m.flow_run_knowledge_best_match())).toBeTruthy();
    });
    // The chip belongs to the -0.2 passage, the true best of the negatives.
    const chip = screen.getByText(m.flow_run_knowledge_best_match());
    expect(chip.closest("li, div")?.textContent).toContain(
      m.flow_run_knowledge_chunk_label({ chunk: "2" })
    );
  });

  it("the viewer footer says shown-of-matched for disclosed passages and explains the gap", async () => {
    render(FlowChunkViewer, {
      eneo: makeEneo(),
      infoBlobId: "11111111-1111-1111-1111-111111111111",
      title: "Källdokument",
      passages: PASSAGES,
      matchedChunkCount: 3,
      children: createRawSnippet((args: () => { showViewer: () => void }) => ({
        render: () => `<button data-testid="open-viewer">open</button>`,
        setup: (element) => {
          element.addEventListener("click", () => args().showViewer());
        }
      }))
    });

    screen.getByTestId("open-viewer").click();

    // One disclosed passage shown of three matched — "saved" language would
    // be wrong here since two were saved but only one is disclosed.
    await waitFor(() => {
      expect(
        screen.getByText(
          m.flow_run_knowledge_chunks_shown_of_matched({ displayed: "1", matched: "3" })
        )
      ).toBeTruthy();
    });
    // The gap between matched and recorded is explained without claiming the
    // hidden segments were used by the AI.
    expect(
      screen.getByText(m.flow_run_knowledge_hidden_matched_explainer({ count: "1" }))
    ).toBeTruthy();
  });
});
