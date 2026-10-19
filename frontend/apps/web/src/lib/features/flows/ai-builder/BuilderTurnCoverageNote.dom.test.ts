import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { formatList } from "$lib/core/formatting/formatList";
import { m } from "$lib/paraglide/messages";

import BuilderTurnCoverageNote from "./BuilderTurnCoverageNote.svelte";
import type { AIBuilderTurnCoverage } from "./protocol";

afterEach(() => cleanup());

const COVERAGE: AIBuilderTurnCoverage = {
  schema_version: 1,
  notes: [
    {
      stage: "classification",
      material: "classification_sources",
      total: 9,
      omitted: 1,
      shortened: 3,
      reasons: ["fixed_limit"]
    },
    {
      stage: "proposal",
      material: "history_messages",
      total: 20,
      omitted: 12,
      shortened: 0,
      reasons: ["model_room"]
    },
    {
      stage: "proposal",
      material: "requirement_assumptions",
      total: 4,
      omitted: 2,
      shortened: 0,
      reasons: ["model_room"]
    }
  ]
};

describe("BuilderTurnCoverageNote", () => {
  // Kills: a material counted under another's words, omitted and shortened
  // swapped, a zero count named, or the singular used for a plural count.
  it("names each material's count in one line", () => {
    render(BuilderTurnCoverageNote, { coverage: COVERAGE });

    expect(screen.getByRole("button").textContent?.trim()).toBe(
      m.ai_builder_coverage_line({
        parts: formatList([
          m.ai_builder_coverage_classification_sources_omitted_one(),
          m.ai_builder_coverage_classification_sources_shortened({ count: "3" }),
          m.ai_builder_coverage_history_messages_omitted({ count: "12" }),
          m.ai_builder_coverage_requirement_assumptions_omitted({ count: "2" })
        ])
      })
    );
  });

  // Kills: the context-window hint under a fixed limit, where a larger model
  // would not help, or missing under a note the model's room cut; a fixed
  // limit left without its reason (gate it1 F1).
  it("lists each note by stage with the reason for each limit", async () => {
    render(BuilderTurnCoverageNote, { coverage: COVERAGE });

    await fireEvent.click(screen.getByRole("button"));

    const title = await screen.findByText(m.ai_builder_coverage_popover_title());
    const items = [...title.closest("[data-slot=popover-content]")!.querySelectorAll("li")];
    expect(items.map((item) => [...item.children].map((part) => part.textContent?.trim()))).toEqual(
      [
        [
          m.ai_builder_coverage_stage_classification(),
          m.ai_builder_coverage_note_detail({
            parts: formatList([
              m.ai_builder_coverage_classification_sources_omitted_one(),
              m.ai_builder_coverage_classification_sources_shortened({ count: "3" })
            ]),
            total: "9"
          }),
          m.ai_builder_coverage_fixed_limit_reason()
        ],
        [
          m.ai_builder_coverage_stage_proposal(),
          m.ai_builder_coverage_note_detail({
            parts: m.ai_builder_coverage_history_messages_omitted({ count: "12" }),
            total: "20"
          }),
          m.ai_builder_coverage_model_room_hint()
        ],
        [
          m.ai_builder_coverage_stage_proposal(),
          m.ai_builder_coverage_note_detail({
            parts: m.ai_builder_coverage_requirement_assumptions_omitted({ count: "2" }),
            total: "4"
          }),
          m.ai_builder_coverage_model_room_hint()
        ]
      ]
    );
  });
});
