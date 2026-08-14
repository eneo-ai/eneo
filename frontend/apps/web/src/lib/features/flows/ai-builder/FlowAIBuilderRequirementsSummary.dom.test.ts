import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowAIBuilderRequirementsSummary from "./FlowAIBuilderRequirementsSummary.svelte";
import type { RequirementsSummary } from "./protocol";

afterEach(() => {
  cleanup();
});

const summary: RequirementsSummary = {
  requirements_version: "v1",
  summary: "Flödet ska ta emot text och leverera ett strukturerat textresultat.",
  key_decisions: [{ topic: "Slutresultat", decision: "Strukturerat textresultat" }],
  input_description: "Text vid körning",
  output_description: "Strukturerat textresultat",
  assumptions: ["Svenska som språk"],
  manual_setup_notes: []
};

describe("FlowAIBuilderRequirementsSummary", () => {
  it("keeps saved-step confirmation focused on the selected step", () => {
    render(FlowAIBuilderRequirementsSummary, {
      summary,
      userRequest: "Lägg till en exakt avslutning.",
      savedFlowStepScope: {
        stepNumber: 2,
        stepName: "Jämför likheter och skillnader"
      }
    });

    expect(
      screen.getByRole("heading", {
        name: m.ai_builder_saved_step_review_heading({ step: 2 })
      })
    ).toBeTruthy();
    expect(screen.getByText("Jämför likheter och skillnader")).toBeTruthy();
    expect(screen.getByText(m.ai_builder_saved_step_review_scope())).toBeTruthy();
    expect(screen.getByText("Lägg till en exakt avslutning.")).toBeTruthy();
    expect(screen.queryByText(summary.summary)).toBeNull();
    expect(screen.queryByText("Slutresultat")).toBeNull();
    expect(screen.queryByText(summary.input_description)).toBeNull();
  });

  it("keeps actionable setup notes visible for a saved-step edit", () => {
    render(FlowAIBuilderRequirementsSummary, {
      summary: {
        ...summary,
        manual_setup_notes: ["Välj jämförelseunderlag innan publicering."]
      },
      savedFlowStepScope: {
        stepNumber: 2,
        stepName: "Jämför likheter och skillnader"
      }
    });

    expect(screen.getByText("Välj jämförelseunderlag innan publicering.")).toBeTruthy();
  });
});
