import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import FlowNodeLlm from "./FlowNodeLlm.svelte";

vi.mock("@xyflow/svelte", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@xyflow/svelte")>()),
  Handle: (await import("./FlowHandleStub.fixture.svelte")).default
}));

afterEach(cleanup);

it.each([
  ["pass_through", true],
  ["copy_input", false],
  ["compose_text", false]
] as const)(
  "names the assistant's model on a %s step only when the step calls it (%s)",
  (outputMode: FlowStep["output_mode"], named: boolean) => {
    // Kills a graph node that shows the assistant's model and model class on a
    // step that calls no completion model.
    render(FlowNodeLlm, {
      props: {
        data: {
          label: "Step",
          step: {
            step_order: 1,
            input_type: "json",
            output_type: "json",
            output_mode: outputMode,
            output_classification_override: null,
            review_policy: null
          },
          isActive: false,
          mode: "power_user",
          modelName: "Model A",
          assistantClassLevel: 2,
          assistantClassName: "Internal",
          classLevel: 2
        }
      }
    });
    expect(screen.queryByText("Model A") !== null).toBe(named);
    expect(screen.queryByText(m.flow_node_model_class_badge({ name: "Internal" })) !== null).toBe(
      named
    );
  }
);
