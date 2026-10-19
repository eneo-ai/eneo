import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { formatList } from "$lib/core/formatting/formatList";
import { m } from "$lib/paraglide/messages";

import BuilderTurnCoverageNote from "./BuilderTurnCoverageNote.svelte";
import type { AIBuilderCoverageNote, AIBuilderTurnCoverage } from "./protocol";

type AIBuilderCountNote = Exclude<AIBuilderCoverageNote, { kind: "tool_catalog_unavailable" }>;

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

describe("BuilderTurnCoverageNote, files, run excerpts and tools", () => {
  const note = (
    stage: "classification" | "proposal",
    material: AIBuilderCountNote["material"],
    omitted: number,
    shortened: number,
    reasons: AIBuilderCountNote["reasons"] = ["model_room"]
  ): AIBuilderCountNote => ({ stage, material, total: 9, omitted, shortened, reasons });
  const UNLISTED_TOOLS = {
    kind: "tool_catalog_unavailable",
    stage: "proposal",
    material: "tool_catalog",
    reason: "catalog_limit"
  } as const;

  // Kills: a material named under another's words or twice (once per stage),
  // a stage that left out less chosen over one that left out more, or the
  // unlisted catalogue left out of the line.
  it("names each material once in the line, by the stage that left out the most", () => {
    render(BuilderTurnCoverageNote, {
      coverage: {
        schema_version: 1,
        notes: [
          note("classification", "attachment_files", 0, 1),
          note("proposal", "history_messages", 0, 2),
          note("proposal", "attachment_files", 2, 0),
          note("proposal", "run_excerpts", 1, 2),
          note("proposal", "usable_tools", 3, 0),
          note("proposal", "tool_schemas", 1, 0),
          note("proposal", "unavailable_tool_names", 2, 0),
          UNLISTED_TOOLS
        ]
      }
    });

    expect(screen.getByRole("button").textContent?.trim()).toBe(
      m.ai_builder_coverage_line({
        parts: formatList([
          m.ai_builder_coverage_attachment_files_omitted({ count: "2" }),
          m.ai_builder_coverage_run_excerpts_omitted_one(),
          m.ai_builder_coverage_usable_tools_omitted({ count: "3" }),
          m.ai_builder_coverage_tool_schemas_omitted_one(),
          m.ai_builder_coverage_unavailable_tool_names_omitted({ count: "2" }),
          m.ai_builder_coverage_tool_catalog_unavailable()
        ])
      })
    );
  });

  // Kills: a shortened-only note left without its words, the organisation's
  // limit unnamed or given the larger-model hint, the unlisted catalogue
  // given counts or a hint, or a turn whose only note has nothing nameable
  // still showing a line.
  it("explains each note by stage and reason in the popover", async () => {
    render(BuilderTurnCoverageNote, {
      coverage: {
        schema_version: 1,
        notes: [
          note("classification", "attachment_files", 0, 1),
          note("proposal", "run_excerpts", 0, 2, ["configured_limit"]),
          UNLISTED_TOOLS
        ]
      }
    });

    await fireEvent.click(screen.getByRole("button"));

    const title = await screen.findByText(m.ai_builder_coverage_popover_title());
    const items = [...title.closest("[data-slot=popover-content]")!.querySelectorAll("li")];
    expect(items.map((item) => [...item.children].map((part) => part.textContent?.trim()))).toEqual(
      [
        [
          m.ai_builder_coverage_stage_classification(),
          m.ai_builder_coverage_note_detail({
            parts: m.ai_builder_coverage_attachment_files_shortened_one(),
            total: "9"
          }),
          m.ai_builder_coverage_model_room_hint()
        ],
        [
          m.ai_builder_coverage_stage_proposal(),
          m.ai_builder_coverage_note_detail({
            parts: m.ai_builder_coverage_run_excerpts_shortened({ count: "2" }),
            total: "9"
          }),
          m.ai_builder_coverage_configured_limit_reason()
        ],
        [
          m.ai_builder_coverage_stage_proposal(),
          m.ai_builder_coverage_tool_catalog_unavailable_detail()
        ]
      ]
    );
    cleanup();

    render(BuilderTurnCoverageNote, {
      coverage: { schema_version: 1, notes: [note("proposal", "history_messages", 0, 2)] }
    });
    expect(screen.queryByRole("button")).toBeNull();
  });
});
