import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRawSnippet } from "svelte";
import { m } from "$lib/paraglide/messages";
import { withLocale } from "../testLocale";
import type { AIBuilderFlowReviewPacket } from "./protocol";
import BuilderFindingsScreen from "./BuilderFindingsScreen.svelte";
import { MAX_FINDINGS_PER_CHANGE } from "./flowReviewFindings";

/** Reading and deciding are separate now: tick the rows, then press the one
 *  action the section shows. */
async function tick(list: "findings-list" | "suggestions-list", ...indexes: number[]) {
  const boxes = screen.getByTestId(list).querySelectorAll<HTMLElement>('[role="checkbox"]');
  for (const index of indexes) await fireEvent.click(boxes[index]);
}

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
      omitted: { other_version: 0, not_viewable: 1, level_unknown: 0, overflow: 0 },
      admission: []
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
    const header = screen.getByTestId("builder-findings").textContent ?? "";
    expect(header).toContain(m.ai_builder_review_lead({ version: "4", total: "4" }));
    expect(header).toContain(m.ai_builder_review_lead_failed({ failed: "1" }));
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
    // The completeness fact is a footnote, never a card, and omitted runs are
    // counted — in the singular when there is one, as the two counters beside
    // it already were.
    expect(screen.getByTestId("builder-findings").textContent).toContain(
      m.ai_builder_review_omitted_one()
    );

    // No action until something is ticked: the list is for reading first.
    expect(screen.queryByTestId("prepare-selected")).toBeNull();

    await tick("findings-list", 0);
    await fireEvent.click(screen.getByTestId("prepare-selected"));
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

  it("takes several findings into one change, and drops a hidden one from the selection", async () => {
    const onprepare = vi.fn();
    render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      onprepare,
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    await fireEvent.click(screen.getByTestId("findings-select-all"));
    await fireEvent.click(screen.getByTestId("prepare-selected"));
    expect(onprepare.mock.calls[0][0].reviewContext.finding_ids).toEqual([
      "aaaaaaaaaaaaaaaa",
      "bbbbbbbbbbbbbbbb"
    ]);

    // Hiding a ticked finding must not leave it voting from off screen.
    const [hide] = screen.getAllByRole("button", { name: m.ai_builder_review_hide() });
    await fireEvent.click(hide);
    await fireEvent.click(screen.getByTestId("prepare-selected"));
    expect(onprepare.mock.calls[1][0].reviewContext.finding_ids).toEqual(["bbbbbbbbbbbbbbbb"]);
  });

  it.each([MAX_FINDINGS_PER_CHANGE, MAX_FINDINGS_PER_CHANGE + 1])(
    "never sends more findings than the server accepts, with %i on screen",
    async (total) => {
      // `finding_ids` is declared max_length=MAX_REVIEW_FINDINGS_PER_TURN on
      // the server, and the fact generator can exceed it on a long flow, so
      // a selection that ignored the bound would build a rejected request.
      const onprepare = vi.fn();
      const packet = makePacket();
      render(BuilderFindingsScreen, {
        review: {
          status: "ready",
          packet: {
            ...packet,
            facts: Array.from({ length: total }, (_, i) => ({
              kind: "output_not_observed_consumed" as const,
              finding_id: `finding-${String(i).padStart(10, "0")}`,
              step_id: STEP_1,
              step_order: 1,
              run_count: 3
            }))
          }
        },
        onprepare,
        onclose: vi.fn(),
        onretry: vi.fn()
      });

      await fireEvent.click(screen.getByTestId("findings-select-all"));
      await fireEvent.click(screen.getByTestId("prepare-selected"));
      const sent = onprepare.mock.calls[0][0].reviewContext.finding_ids;
      expect(sent).toHaveLength(MAX_FINDINGS_PER_CHANGE);

      // Over the bound, the remaining rows stop being tickable and the screen
      // says why rather than letting someone build a request that fails.
      const boxes = screen
        .getByTestId("findings-list")
        .querySelectorAll<HTMLButtonElement>('[role="checkbox"]');
      const unticked = [...boxes].filter((b) => b.getAttribute("aria-checked") !== "true");
      expect(unticked.every((b) => b.disabled)).toBe(true);
      expect(unticked).toHaveLength(total - MAX_FINDINGS_PER_CHANGE);
    }
  );

  it("explains withheld token measurements in the completeness footer", () => {
    const packet = makePacket();
    render(BuilderFindingsScreen, {
      review: {
        status: "ready",
        packet: {
          ...packet,
          facts: packet.facts.map((fact) =>
            fact.kind === "evidence_completeness"
              ? { ...fact, runs_missing_step_results: 0, runs_with_usage_withheld: 2 }
              : fact
          )
        }
      },
      onprepare: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    const footer = screen.getByRole("contentinfo").textContent ?? "";
    expect(footer).toContain(m.ai_builder_review_usage_withheld({ count: "2" }));
    expect(footer).not.toContain(m.ai_builder_review_completeness_one());
  });

  it("hides a finding for this flow and offers to show it again", async () => {
    const { unmount } = render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      onprepare: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    const status = () =>
      screen.getByTestId("builder-findings").querySelector('[role="status"]')?.textContent ?? "";

    const [hide] = screen.getAllByRole("button", { name: m.ai_builder_review_hide() });
    await fireEvent.click(hide);
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: m.ai_builder_review_show_hidden_one() })
    ).toBeTruthy();
    // The announcement has to agree with the restore button. `hiddenCount` is
    // derived from `dismissed`, so reading it after the assignment already
    // counts the finding just hidden; adding one announced two.
    expect(status()).toBe(m.ai_builder_review_hidden_notice());

    // And it has to change on the second hide, or a polite live region with
    // unchanged content is never re-announced.
    const [hideSecond] = screen.getAllByRole("button", { name: m.ai_builder_review_hide() });
    await fireEvent.click(hideSecond);
    expect(status()).toBe(m.ai_builder_review_hidden_notice_count({ count: "2" }));
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_review_show_hidden({ count: "2" }) })
    );
    await fireEvent.click(screen.getAllByRole("button", { name: m.ai_builder_review_hide() })[0]);
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
      screen.getByRole("button", { name: m.ai_builder_review_show_hidden_one() })
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
            omitted: { other_version: 2, not_viewable: 0, level_unknown: 0, overflow: 0 },
            admission: []
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
      model_name: "Model A",
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
    expect(screen.getByText(m.ai_builder_review_suggestions_hint())).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_review_suggest() }));
    expect(onsuggest).toHaveBeenCalledTimes(1);
  });

  it.each(["sv", "en"] as const)(
    "names what crosses each boundary before the call and beside the action (%s)",
    async (locale) => {
      // What is sent to the model before the call: the recorded fields and
      // the recipient. What travels on investigate: reference metadata, never
      // the reasoning or the quotes. Concepts, not sentences, in both locales.
      const restoreLocale = withLocale(locale);
      try {
        const closed = render(BuilderFindingsScreen, {
          review: { status: "ready", packet: makePacket() },
          suggestions: { status: "closed" },
          onprepare: vi.fn(),
          onsuggest: vi.fn(),
          onclose: vi.fn(),
          onretry: vi.fn()
        });
        const hint = screen.getByTestId("review-suggestions").textContent ?? "";
        expect(hint).toMatch(/instruktioner|instructions/i);
        expect(hint).toMatch(/indata|inputs/i);
        expect(hint).toMatch(/utdata|outputs/i);
        expect(hint).toMatch(/planeringsmodell|planning model/i);
        closed.unmount();

        render(BuilderFindingsScreen, {
          review: { status: "ready", packet: makePacket() },
          suggestions: { status: "ready", suggestions: makeSuggestions() },
          onprepare: vi.fn(),
          onsuggest: vi.fn(),
          onclose: vi.fn(),
          onretry: vi.fn()
        });
        // The disclosure is one click behind a question that names it, so
        // the reader always sees that there is one. Open it and read it: it
        // describes the section, so with nothing ticked it is the plural
        // wording. Concepts are what matters here, not the sentence.
        await fireEvent.click(screen.getByTestId("suggestions-sends"));
        const note =
          screen.getByText(m.ai_builder_review_suggestion_investigate_all_hint()).textContent ?? "";
        expect(note).toMatch(/motivering|reasoning/i);
        expect(note).toMatch(/citat|quotes/i);
        // The investigation rereads the named runs and takes bounded excerpts
        // of them to the planner, so the note has to say so: it is the only
        // place the user is told what leaves this screen.
        // The concept, not the sentence: the runs are read a second time.
        // "läser om" was replaced because in Swedish it reads as "reads
        // about" as readily as "re-reads", in the one sentence that governs
        // whether case content leaves the tenancy.
        expect(note).toMatch(/en gång till|once more/i);
        expect(note).toMatch(/utdrag|excerpts/i);
        await tick("suggestions-list", 0);
        expect(screen.getByText(m.ai_builder_review_suggestion_investigate_hint())).toBeTruthy();
      } finally {
        restoreLocale();
      }
    }
  );

  it("shows suggestions with their quotes folded and sends reference metadata onward, never the reasoning or quotes", async () => {
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
    // The quotes are evidence, folded until asked for; the finding reads first.
    const sourceCount = makeSuggestions().suggestions[0].sources.length;
    await fireEvent.click(
      screen.getByRole("button", {
        name:
          sourceCount === 1
            ? m.ai_builder_review_suggestion_sources_show_one()
            : m.ai_builder_review_suggestion_sources_show({ count: String(sourceCount) })
      })
    );
    expect(section.textContent).toContain("tre punkter");
    expect(section.textContent).toContain(
      m.ai_builder_review_suggestion_source({
        run: "2",
        step: "2",
        field: m.ai_builder_review_suggestion_field_prompt()
      })
    );
    expect(section.textContent).toContain(m.ai_builder_review_suggestions_lead({ runs: "2" }));
    expect(section.textContent).toContain(m.ai_builder_review_suggestions_partly_read());
    // How much was read, and by which model, sits behind the info control as
    // its accessible name: a consequence in plain words, with the whole.
    const coverage = m.ai_builder_review_suggestions_coverage_truncated_unread({
      total: "9",
      truncated: "1",
      unread: "3"
    });
    const readingNote = screen
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label") ?? "")
      .find((label) => label.includes(coverage));
    expect(readingNote).toContain("Model A");

    await tick("suggestions-list", 0);
    await fireEvent.click(screen.getByTestId("investigate-selected"));
    expect(onprepare).toHaveBeenCalledTimes(1);
    const detail = onprepare.mock.calls[0][0];
    expect(detail.reviewContext).toEqual({
      kind: "flow_review_suggestion",
      flow_version: 4,
      definition_checksum: "sum-4",
      sample_run_ids: [RUN_1, RUN_2],
      suggestions: [{ suggestion_kind: "duplicated_work", step_orders: [1, 2] }]
    });
    // The handoff never carries the rationale or a quote.
    expect(detail.message).not.toContain("tre punkter");
    expect(detail.message).not.toContain("sammanfattar");
    expect(detail.message).toContain("1 och 2");
  });

  it.each([
    {
      locale: "sv" as const,
      all: "Undersök följande utifrån körningarna: möjligt dubbelarbete i steg 1 och 2; en kontroll som kan saknas i steg 3.",
      one: "Undersök möjligt dubbelarbete i steg 1 och 2 utifrån körningarna."
    },
    {
      locale: "en" as const,
      all: "Investigate the following based on the runs: possible duplicated work in steps 1 and 2; a check that may be missing in step 3.",
      one: "Investigate possible duplicated work in steps 1 and 2 based on the runs."
    }
  ])(
    "investigates every suggestion in one canonical turn, or just one, in $locale",
    async ({ locale, all, one }) => {
      const restoreLocale = withLocale(locale);
      try {
        const onprepare = vi.fn();
        const judged = makeSuggestions();
        const second = {
          ...judged.suggestions[0],
          kind: "missing_check" as const,
          step_orders: [3],
          rationale: "Ingen kontroll av tomma svar.",
          sources: [judged.suggestions[0].sources[0]]
        };
        // Reversed order and two findings on one scope; one canonical set of scopes leaves it.
        render(BuilderFindingsScreen, {
          review: { status: "ready", packet: makePacket() },
          suggestions: {
            status: "ready",
            suggestions: {
              ...judged,
              suggestions: [
                second,
                judged.suggestions[0],
                { ...judged.suggestions[0], rationale: "Samma steg, annan läsning." }
              ]
            }
          },
          onprepare,
          onsuggest: vi.fn(),
          onclose: vi.fn(),
          onretry: vi.fn()
        });
        const note = screen.getByTestId("review-suggestions").textContent ?? "";
        expect(note).toMatch(/förslagens typer|suggestions' kinds/i);

        await fireEvent.click(screen.getByTestId("suggestions-select-all"));
        await fireEvent.click(screen.getByTestId("investigate-selected"));
        expect(onprepare).toHaveBeenCalledTimes(1);
        const batch = onprepare.mock.calls[0][0];
        expect(batch.reviewContext.suggestions).toEqual([
          { suggestion_kind: "duplicated_work", step_orders: [1, 2] },
          { suggestion_kind: "missing_check", step_orders: [3] }
        ]);
        // The exact sentence the server retains, in the screen's language.
        expect(batch.message).toBe(all);
        expect(batch.message).not.toContain("tre punkter");
        expect(batch.message).not.toContain("tomma svar");

        // Each row's checkbox carries its own accessible name, including its
        // ordinal, so two findings on one scope stay two distinct choices.
        const stepsOneTwo = m.ai_builder_review_suggestion_steps({
          steps: `1 ${m.ai_builder_review_suggestion_steps_join()} 2`
        });
        const kindDuplicated = m.ai_builder_review_suggestion_kind_duplicated_work();
        const secondCard = screen.getByRole("checkbox", {
          name: m.ai_builder_review_suggestion_investigate_this_label({
            index: "2",
            kind: kindDuplicated,
            steps: stepsOneTwo
          })
        });
        const thirdCard = screen.getByRole("checkbox", {
          name: m.ai_builder_review_suggestion_investigate_this_label({
            index: "3",
            kind: kindDuplicated,
            steps: stepsOneTwo
          })
        });
        expect(secondCard).not.toBe(thirdCard);
        await fireEvent.click(screen.getByTestId("suggestions-select-all")); // clear
        await fireEvent.click(thirdCard);
        await fireEvent.click(screen.getByTestId("investigate-selected"));
        const single = onprepare.mock.calls[1][0];
        expect(single.reviewContext.suggestions).toEqual([
          { suggestion_kind: "duplicated_work", step_orders: [1, 2] }
        ]);
        expect(single.message).toBe(one);
      } finally {
        restoreLocale();
      }
    }
  );

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
      m.ai_builder_review_suggestions_lead_one()
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

  it("keeps the model controls and a retry when the chosen model may not read the sample", () => {
    const controls = createRawSnippet(() => ({
      render: () => `<span data-testid="planner-controls">controls</span>`
    }));
    render(BuilderFindingsScreen, {
      review: { status: "ready", packet: makePacket() },
      suggestions: {
        status: "failed",
        error: {
          code: "planner_model_below_evidence_level",
          message: "The planner model may not read runs at this level.",
          category: "bad_request",
          phase: "router",
          transient: false
        } as never
      },
      plannerControls: controls,
      onprepare: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    expect(screen.getByText(m.ai_builder_review_suggestions_below_level())).toBeTruthy();
    expect(screen.getByRole("button", { name: m.ai_builder_review_retry() })).toBeTruthy();
    expect(screen.getByTestId("planner-controls")).toBeTruthy();
  });
});
