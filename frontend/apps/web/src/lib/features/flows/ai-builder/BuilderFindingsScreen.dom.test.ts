import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { AIBuilderFlowReviewPacket } from "./protocol";
import BuilderFindingsScreen from "./BuilderFindingsScreen.svelte";

const STEP_1 = "11111111-1111-4111-8111-111111111111";
const STEP_2 = "22222222-2222-4222-8222-222222222222";

function makePacket(overrides: Partial<AIBuilderFlowReviewPacket> = {}): AIBuilderFlowReviewPacket {
  return {
    flow_id: "flow-1",
    flow_version: 4,
    definition_checksum: "sum-4",
    generated_at: "2026-09-04T12:00:00Z",
    evidence_classification_level: 0,
    steps: [
      { step_id: STEP_1, step_order: 1, label: "Transkribera" },
      { step_id: STEP_2, step_order: 2, label: "Sammanfatta" }
    ],
    cohort: {
      completed_run_ids: ["r1", "r2", "r3"],
      failed_run_ids: ["r4"],
      omitted: { other_version: 0, not_viewable: 1, level_unknown: 0 }
    },
    facts: [
      {
        kind: "output_not_observed_consumed",
        finding_id: "aaaaaaaaaaaaaaaa",
        step_id: STEP_1,
        step_order: 1,
        run_count: 3
      },
      {
        kind: "token_share",
        finding_id: "bbbbbbbbbbbbbbbb",
        step_id: STEP_2,
        step_order: 2,
        share: 0.82,
        run_count: 3
      },
      {
        kind: "evidence_completeness",
        finding_id: "cccccccccccccccc",
        runs_with_all_step_results: 3,
        runs_missing_step_results: 1,
        runs_without_lineage: 1
      }
    ],
    ...overrides
  };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("BuilderFindingsScreen", () => {
  it("shows each finding as a card and sends the named finding when a change is prepared", async () => {
    const onprepare = vi.fn();
    render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      onprepare,
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(
      screen.getByText(m.ai_builder_review_lead({ version: "4", completed: "3", failed: "1" }))
    ).toBeTruthy();
    const cards = screen.getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    expect(
      screen.getByText(
        m.ai_builder_review_unconsumed_title({
          step: m.ai_builder_review_step_labelled({ number: "1", label: "Transkribera" })
        })
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        m.ai_builder_review_token_share_title({
          step: m.ai_builder_review_step_labelled({ number: "2", label: "Sammanfatta" }),
          percent: "82"
        })
      )
    ).toBeTruthy();
    // The completeness fact is a footnote, never a card, and omitted runs are counted.
    expect(screen.getByTestId("builder-findings").textContent).toContain(
      m.ai_builder_review_omitted({ count: "1" })
    );

    const [prepare] = screen.getAllByRole("button", { name: m.ai_builder_review_prepare() });
    await fireEvent.click(prepare);
    expect(onprepare).toHaveBeenCalledWith({
      message: m.ai_builder_review_prepare_message({
        finding: m.ai_builder_review_unconsumed_title({
          step: m.ai_builder_review_step_labelled({ number: "1", label: "Transkribera" })
        })
      }),
      reviewContext: {
        kind: "flow_review",
        flow_version: 4,
        definition_checksum: "sum-4",
        finding_ids: ["aaaaaaaaaaaaaaaa"]
      }
    });
  });

  it("hides a finding for this flow and offers to show it again", async () => {
    const { unmount } = render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      onprepare: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    const [hide] = screen.getAllByRole("button", { name: m.ai_builder_review_hide() });
    await fireEvent.click(hide);
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: m.ai_builder_review_show_hidden({ count: "1" }) })
    ).toBeTruthy();
    unmount();
    // A hidden finding stays hidden on the next open of the same version.
    render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      onprepare: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_review_show_hidden({ count: "1" }) })
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("explains an unpublished flow and a flow without runs in words", () => {
    const { unmount } = render(BuilderFindingsScreen, {
      review: {
        status: "failed",
        error: {
          code: "flow_not_published",
          message: "The flow has no published version to review runs of.",
          category: "bad_request",
          phase: "router",
          transient: false
        } as never
      },
      onprepare: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.getByText(m.ai_builder_review_unpublished_title())).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_review_retry() })).toBeNull();
    unmount();
    render(BuilderFindingsScreen, {
      review: {
        status: "ready",
        packet: makePacket({
          cohort: {
            completed_run_ids: [],
            failed_run_ids: [],
            omitted: { other_version: 2, not_viewable: 0, level_unknown: 0 }
          },
          facts: []
        })
      },
      onprepare: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.getByTestId("findings-no-runs")).toBeTruthy();
  });
});
