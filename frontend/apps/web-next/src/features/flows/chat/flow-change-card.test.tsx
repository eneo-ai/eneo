// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import { makeFlow } from "../flow-fixtures";
import { FlowChangeCard, changedSteps, flowChangeCardFor } from "./flow-change-card";
import { FlowReferences } from "./reference-pill";

afterEach(cleanup);

const CHANGES = [
  {
    step_id: "step-2",
    step_order: 2,
    name: "Skriv svaret",
    fields: [
      {
        field: "assistant.prompt",
        before: "Sammanfatta brevet.",
        after: "Sammanfatta brevet i tre punkter."
      },
      { field: "output_type", before: "text", after: "json" },
      { field: "mystery", before: null, after: true }
    ]
  }
];

function call(overrides: Partial<ToolCallRecord> = {}): ToolCallRecord {
  return {
    toolCallId: "call-1",
    toolName: "update_steps",
    state: "output-available",
    input: {},
    serverName: "flows",
    title: null,
    purpose: null,
    isInternal: true,
    isBundled: false,
    appView: null,
    approved: true,
    resultStatus: "succeeded",
    generatedFileIds: [],
    structuredContent: { flow_id: "flow-1", draft_revision: 5, changes: CHANGES },
    part: {
      type: "dynamic-tool",
      toolName: "update_steps",
      toolCallId: "call-1",
      state: "output-available",
      input: {},
      output: {}
    },
    ...overrides
  };
}

describe("changedSteps", () => {
  it("reads the steps a change of the flow chat touched, and nothing from other calls", () => {
    expect(changedSteps(call())).toEqual([
      {
        stepId: "step-2",
        stepOrder: 2,
        name: "Skriv svaret",
        fields: CHANGES[0]!.fields
      }
    ]);
    expect(changedSteps(call({ toolName: "update_step" }))).toHaveLength(1);
    // A read, an external server named "flows", a change without steps, and
    // a step whose every field kept its value give no card.
    expect(changedSteps(call({ toolName: "read_flow" }))).toEqual([]);
    expect(changedSteps(call({ isInternal: false }))).toEqual([]);
    expect(changedSteps(call({ structuredContent: { flow_id: "flow-1" } }))).toEqual([]);
    expect(
      changedSteps(
        call({ structuredContent: { changes: [{ step_id: "step-2", step_order: 2, fields: [] }] } })
      )
    ).toEqual([]);
    expect(flowChangeCardFor(call({ toolName: "run_flow" }))).toBeNull();
  });
});

describe("FlowChangeCard", () => {
  it("shows each changed field before and after, named as the editor names it", async () => {
    const { container } = renderInApp(<FlowChangeCard steps={changedSteps(call())} />);
    const card = screen.getByRole("region", { name: "Ändrade 1 steg" });
    expect(
      within(card).getByRole("button", { name: /Steg 2: Skriv svaret · 3 fält/ })
    ).toBeTruthy();
    // One changed step is open at once.
    expect(within(card).getByText("Instruktion")).toBeTruthy();
    expect(within(card).getByText("Sammanfatta brevet.")).toBeTruthy();
    expect(within(card).getByText("Sammanfatta brevet i tre punkter.")).toBeTruthy();
    expect(within(card).getByText("Resultattyp")).toBeTruthy();
    // A field the card cannot name shows by its own name; nothing shows as "(tomt)".
    expect(within(card).getByText("mystery")).toBeTruthy();
    expect(within(card).getByText("(tomt)")).toBeTruthy();
    expect(within(card).getByText("Ja")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Visa steget" })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("folds several steps and brings a step into view through the page's references", () => {
    const onShowStep = vi.fn(() => true);
    const steps = [
      ...changedSteps(call()),
      {
        stepId: "step-3",
        stepOrder: 3,
        name: null,
        fields: [{ field: "user_description", before: null, after: "Granska" }]
      }
    ];
    renderInApp(
      <FlowReferences flow={makeFlow()} onShowStep={onShowStep}>
        <FlowChangeCard steps={steps} />
      </FlowReferences>
    );
    const card = screen.getByRole("region", { name: "Ändrade 2 steg" });
    const third = within(card).getByRole("button", { name: /Steg 3 · 1 fält/ });
    expect(third.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(third);
    expect(within(card).getByText("Granska")).toBeTruthy();
    // The third step's own action, after the second's.
    fireEvent.click(within(card).getAllByRole("button", { name: "Visa steget" }).at(-1)!);
    expect(onShowStep).toHaveBeenCalledWith("step-3");
  });
});
