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
      omitted: { other_version: 0, not_viewable: 1, level_unknown: 0, overflow: 0 }
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
    const large = render(BuilderFindingsScreen, {
      review: {
        status: "failed",
        error: {
          code: "review_flow_too_large",
          message: "The flow has more steps than a run review reads.",
          category: "bad_request",
          phase: "router",
          transient: false
        } as never
      },
      onprepare: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.getByText(m.ai_builder_review_flow_too_large_title())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_review_flow_too_large())).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_review_retry() })).toBeNull();
    large.unmount();
    render(BuilderFindingsScreen, {
      review: {
        status: "ready",
        packet: makePacket({
          cohort: {
            completed_run_ids: [],
            failed_run_ids: [],
            omitted: { other_version: 2, not_viewable: 0, level_unknown: 0, overflow: 0 }
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

describe("BuilderFindingsScreen suggestions", () => {
  const RUN_1 = "r1";
  const RUN_2 = "r4";

  function makeSuggestions() {
    return {
      model_id: "model-1",
      model_name: "GPT-test",
      unverified_count: 0,
      generated_at: "2026-09-05T12:00:00Z",
      flow_version: 4,
      definition_checksum: "sum-4",
      evidence_classification_level: 2,
      sample: {
        run_ids: [RUN_1, RUN_2],
        excerpts_included: 5,
        excerpts_truncated: 1,
        excerpts_omitted_by_budget: 0,
        excerpts_omitted_by_reader: 1,
        excerpts_not_recorded: 2,
        excerpts_unavailable: 0
      },
      suggestions: [
        {
          kind: "duplicated_work" as const,
          step_orders: [2, 1],
          rationale: "Steg 2 sammanfattar det steg 1 redan sammanfattade.",
          sources: [
            { run_id: RUN_1, step_order: 1, field: "output" as const, quote: "tre punkter" },
            { run_id: RUN_2, step_order: 2, field: "prompt" as const, quote: "Sammanfatta ärendet" }
          ],
          fact_ids: []
        }
      ]
    };
  }

  it("offers the model judgement behind one button that names what it reads", async () => {
    const onsuggest = vi.fn();
    render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      suggestions: { status: "closed" },
      onprepare: vi.fn(),
      onsuggest,
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.getByText(m.ai_builder_review_suggest_hint())).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_review_suggest() }));
    expect(onsuggest).toHaveBeenCalledTimes(1);
  });

  it("shows suggestions with their sources and sends only kind and steps onward", async () => {
    const onprepare = vi.fn();
    render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      suggestions: { status: "ready", suggestions: makeSuggestions() },
      onprepare,
      onsuggest: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    const section = screen.getByTestId("review-suggestions");
    expect(section.textContent).toContain(m.ai_builder_review_suggestion_kind_duplicated_work());
    expect(section.textContent).toContain(
      m.ai_builder_review_suggestion_steps({ steps: "1 och 2" })
    );
    expect(section.textContent).toContain("tre punkter");
    expect(section.textContent).toContain(
      m.ai_builder_review_suggestion_source({
        run: "2",
        step: "2",
        field: m.ai_builder_review_suggestion_field_prompt()
      })
    );
    expect(section.textContent).toContain(
      m.ai_builder_review_suggestions_lead({
        model: "GPT-test",
        runs: "2",
        included: "5",
        truncated: "1",
        unread: "3"
      })
    );

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_review_suggestion_investigate() })
    );
    expect(onprepare).toHaveBeenCalledTimes(1);
    const detail = onprepare.mock.calls[0][0];
    expect(detail.reviewContext).toEqual({
      kind: "flow_review_suggestion",
      flow_version: 4,
      definition_checksum: "sum-4",
      sample_run_ids: [RUN_1, RUN_2],
      suggestion_kind: "duplicated_work",
      step_orders: [2, 1]
    });
    // The handoff never carries the rationale or a quote.
    expect(detail.message).not.toContain("tre punkter");
    expect(detail.message).not.toContain("sammanfattar");
    expect(detail.message).toContain("1 och 2");
  });

  it("distinguishes an empty judgement from a failed one", async () => {
    const { unmount } = render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      suggestions: {
        status: "ready",
        suggestions: {
          ...makeSuggestions(),
          sample: { ...makeSuggestions().sample, run_ids: [RUN_1] },
          suggestions: []
        }
      },
      onprepare: vi.fn(),
      onsuggest: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.getByTestId("suggestions-none")).toBeTruthy();
    // One sampled run reads as one run, not "1 runs".
    expect(screen.getByTestId("review-suggestions").textContent).toContain(
      m.ai_builder_review_suggestions_lead_one({
        model: "GPT-test",
        included: "5",
        truncated: "1",
        unread: "3"
      })
    );
    unmount();

    // Suggestions the model made but could not tie to the runs are a third
    // state: not "nothing found", not a failure, and they invite a retry.
    const onsuggest = vi.fn();
    const unverifiedOnly = render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      suggestions: {
        status: "ready",
        suggestions: { ...makeSuggestions(), suggestions: [], unverified_count: 3 }
      },
      onprepare: vi.fn(),
      onsuggest,
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.queryByTestId("suggestions-none")).toBeNull();
    expect(screen.getByTestId("suggestions-unverified").textContent).toContain(
      m.ai_builder_review_suggestions_all_unverified({ count: "3" })
    );
    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_review_retry() }));
    expect(onsuggest).toHaveBeenCalledTimes(1);
    unverifiedOnly.unmount();

    const partly = render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      suggestions: {
        status: "ready",
        suggestions: { ...makeSuggestions(), unverified_count: 1 }
      },
      onprepare: vi.fn(),
      onsuggest: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.getByTestId("suggestions-list")).toBeTruthy();
    expect(screen.getByTestId("suggestions-some-unverified").textContent).toContain(
      m.ai_builder_review_suggestions_some_unverified_one()
    );
    partly.unmount();

    render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      suggestions: {
        status: "failed",
        error: {
          schema_version: 2,
          code: "review_suggestions_invalid_output",
          category: "bad_request",
          message: "The review model's answer did not resolve in the sampled evidence.",
          phase: "router",
          request_id: null,
          diagnostic_context: null,
          details: {}
        }
      },
      onprepare: vi.fn(),
      onsuggest: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.getByText(m.ai_builder_review_suggestions_invalid_output())).toBeTruthy();
    expect(screen.getByRole("button", { name: m.ai_builder_review_retry() })).toBeTruthy();
  });
});
