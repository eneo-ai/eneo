import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import BuilderBuildScreen from "./BuilderBuildScreen.svelte";

afterEach(() => cleanup());

const thirtySteps = Array.from({ length: 30 }, (_, index) => ({
  id: `step-${index + 1}`,
  name: `Steg nummer ${index + 1}`,
  order: index + 1,
  reads: index === 0 ? "Läser flödets indata" : "Läser föregående steg"
}));

describe("BuilderBuildScreen", () => {
  it("keeps a one-step change's step and its neighbours, and folds the rest", () => {
    render(BuilderBuildScreen, {
      props: { status: null, mode: "edit", flowSteps: thirtySteps, targetStepNumber: 12 }
    });

    for (const order of [11, 12, 13]) {
      expect(screen.getByText(`Steg nummer ${order}`)).toBeTruthy();
    }
    expect(screen.queryByText("Steg nummer 10")).toBeNull();
    expect(screen.getByText(m.ai_builder_diagram_gap({ first: "1", last: "10" }))).toBeTruthy();
    expect(screen.getByText(m.ai_builder_diagram_gap({ first: "14", last: "30" }))).toBeTruthy();
    // Each row says what its step reads, in the step list's words.
    expect(screen.getAllByText("Läser föregående steg")).toHaveLength(3);
    expect(screen.getAllByText(m.ai_builder_node_changes())).toHaveLength(1);
  });

  it("keeps a short flow whole: two unchanged steps are not worth a fold", () => {
    // Folding two steps hides them behind a click and saves one row. Short
    // flows are read at a glance, so the run stays open.
    render(BuilderBuildScreen, {
      props: {
        status: null,
        mode: "edit",
        flowSteps: thirtySteps.slice(0, 4),
        targetStepNumber: 4
      }
    });

    for (const order of [1, 2, 3, 4]) {
      expect(screen.getByText(`Steg nummer ${order}`)).toBeTruthy();
    }
    expect(screen.queryByText(m.ai_builder_diagram_gap({ first: "1", last: "2" }))).toBeNull();
  });

  it("shows a whole-flow change's first steps and counts the rest in one row", () => {
    render(BuilderBuildScreen, {
      props: { status: null, mode: "edit", flowSteps: thirtySteps, targetStepNumber: null }
    });

    expect(screen.getByText("Steg nummer 6")).toBeTruthy();
    expect(screen.queryByText("Steg nummer 7")).toBeNull();
    expect(
      screen.getByText(m.ai_builder_build_more_steps({ first: "7", last: "30" }))
    ).toBeTruthy();
  });
});
