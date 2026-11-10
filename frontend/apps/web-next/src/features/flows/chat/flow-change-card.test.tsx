// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import messages from "@/lib/i18n/messages/sv.json";
import { makeFlow, makeStep } from "../flow-fixtures";
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
    // An enum value reads as the editor names it, under the editor's label.
    expect(within(card).getByText(messages.flow_step_output_type)).toBeTruthy();
    expect(within(card).getByText(messages.flow_output_type_text)).toBeTruthy();
    expect(within(card).getByText(messages.flow_output_type_json)).toBeTruthy();
    expect(within(card).queryByText("json")).toBeNull();
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

function cardFor(fields: { field: string; before: unknown; after: unknown }[]) {
  return changedSteps(
    call({ structuredContent: { changes: [{ step_id: "step-2", step_order: 2, fields }] } })
  );
}

describe("FlowChangeCard's values", () => {
  it("says a delivery's address and settings in words, only the parts that changed", () => {
    const http = (url: string) => ({
      url,
      auth: { mode: "none" },
      timeout_seconds: 30,
      body: { mode: "auto" },
      response_format: "text"
    });
    renderInApp(
      <FlowChangeCard
        steps={cardFor([
          { field: "output_mode", before: "pass_through", after: "http_post" },
          { field: "output_config", before: http(""), after: http("https://arende.kommun.se/in") }
        ])}
      />
    );
    expect(screen.getByText(messages.flow_output_mode_pass_through)).toBeTruthy();
    expect(screen.getByText(messages.flow_output_mode_http_post)).toBeTruthy();
    expect(
      screen.getByText(`${messages.flow_step_editor_http_url_post}: https://arende.kommun.se/in`)
    ).toBeTruthy();
    expect(screen.getByText(`${messages.flow_step_editor_http_url_post}: (tomt)`)).toBeTruthy();
    // What stayed the same (the sign-in, the body, the time limit) is left out.
    expect(screen.queryByText(new RegExp(messages.flow_step_editor_http_auth))).toBeNull();
    expect(screen.queryByText(/\{"url"/)).toBeNull();
  });

  it("names a Word field by its tag and folds a long value until Visa hela", () => {
    const long = "Sammanfatta mötet. ".repeat(20);
    renderInApp(
      <FlowChangeCard
        steps={cardFor([
          {
            field: "output_config",
            before: { template_asset_id: "t-1", template_name: "Protokoll.docx", bindings: {} },
            after: {
              template_asset_id: "t-1",
              template_name: "Protokoll.docx",
              bindings: { deltagare: "{{step_1.output.text}}" }
            }
          },
          { field: "assistant.prompt", before: "Kort.", after: long }
        ])}
      />
    );
    expect(screen.getByText("deltagare: {{step_1.output.text}}")).toBeTruthy();
    // The template itself did not change.
    expect(screen.queryByText(/Protokoll\.docx/)).toBeNull();
    // The field was added: before, there was none.
    expect(screen.getByText(messages.flows_change_card_empty)).toBeTruthy();
    // The button's name says what it does; it carries no expanded state on top.
    const more = screen.getByRole("button", { name: messages.flows_change_card_show_all });
    expect(more.hasAttribute("aria-expanded")).toBe(false);
    // Folded, the instruction is clamped to four lines; open, it shows whole.
    expect(document.querySelector(".line-clamp-4")).not.toBeNull();
    fireEvent.click(more);
    expect(document.querySelector(".line-clamp-4")).toBeNull();
    expect(screen.getByRole("button", { name: messages.flows_change_card_show_less })).toBeTruthy();
    // A short value has nothing more to show.
    expect(screen.getAllByRole("button", { name: /Visa/ })).toHaveLength(1);
  });

  it("opens the step at the changed field", () => {
    const onShowStep = vi.fn(() => true);
    const onConnectStep = vi.fn();
    const flow = makeFlow({ steps: [makeStep(1), makeStep(2)] });
    renderInApp(
      <FlowReferences flow={flow} onShowStep={onShowStep} onConnectStep={onConnectStep}>
        <FlowChangeCard
          steps={cardFor([{ field: "assistant.prompt", before: "Kort.", after: "Längre." }])}
        />
      </FlowReferences>
    );
    fireEvent.click(screen.getByRole("button", { name: "Visa steget" }));
    expect(onConnectStep).toHaveBeenCalledWith("step-2", "prompt");
    expect(onShowStep).not.toHaveBeenCalled();
  });
});
