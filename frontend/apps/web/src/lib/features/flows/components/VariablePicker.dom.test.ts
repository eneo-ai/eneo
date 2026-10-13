import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import VariablePicker from "./VariablePicker.svelte";
import { flowStepFixture } from "$lib/features/flows/flowStepTestFixture";
import { VARIABLE_CATEGORY_CLASSES } from "$lib/features/flows/flowVariableTokens";

// The command list scrolls the active option into view, which jsdom lacks.
beforeAll(() => {
  Element.prototype.scrollIntoView ??= vi.fn();
});

afterEach(async () => {
  cleanup();
  await vi.waitFor(() => {
    expect(document.body.style.overflow).not.toBe("hidden");
  });
});

describe("VariablePicker", () => {
  it("offers the upload on an upload step, coloured as the editor colours it", async () => {
    render(VariablePicker, {
      steps: [],
      currentStepOrder: 1,
      formSchema: undefined,
      isAdvancedMode: true,
      uploadVariableAvailable: true,
      classifyToken: (token: string) => (token === "step_input.text" ? "technical" : "field"),
      onInsert: vi.fn()
    });
    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga från flödet|Insert from the flow)$/ })
    );
    expect(
      screen.getByRole("combobox", { name: /Sök fält och resultat|Search fields and results/ })
    ).toBeTruthy();
    const option = await screen.findByRole("option", {
      name: /Det uppladdade underlaget|The uploaded material/
    });
    const chip = option.querySelector("code");
    expect(chip?.className).toContain(VARIABLE_CATEGORY_CLASSES.technical.scopeClass);
    // The run group alone would have made it purple; the classifier decides.
    expect(chip?.className).not.toContain(VARIABLE_CATEGORY_CLASSES.system.scopeClass);
    expect(chip?.textContent).toBe("{{step_input.text}}");
  });

  it("offers the submitted text only when the run collects neither fields nor an upload", async () => {
    const uploadStep = {
      step_order: 1,
      input_config: { runtime_input: { enabled: true, input_format: "document" } }
    };
    const cases = [
      { steps: [], uploadVariableAvailable: false, offered: true, formSchema: undefined },
      { steps: [], uploadVariableAvailable: false, offered: true, formSchema: { fields: [] } },
      { steps: [], uploadVariableAvailable: true, offered: false, formSchema: undefined },
      {
        steps: [uploadStep],
        uploadVariableAvailable: false,
        offered: false,
        formSchema: undefined
      },
      // The backend's FlowRunInput counts every declared row, usable or not.
      {
        steps: [],
        uploadVariableAvailable: false,
        offered: false,
        formSchema: { fields: [{ name: "", type: "text" }] }
      },
      {
        steps: [],
        uploadVariableAvailable: false,
        offered: false,
        formSchema: { fields: [{ name: "flow_input", type: "text" }] }
      }
    ];
    for (const { steps, uploadVariableAvailable, offered, formSchema } of cases) {
      const { unmount } = render(VariablePicker, {
        steps: steps as never,
        currentStepOrder: 2,
        formSchema,
        isAdvancedMode: true,
        uploadVariableAvailable,
        onInsert: vi.fn()
      });
      await fireEvent.click(
        screen.getByRole("button", { name: /^(Infoga från flödet|Insert from the flow)$/ })
      );
      await screen.findByRole("combobox", {
        name: /Sök fält och resultat|Search fields and results/
      });
      const option = screen.queryByRole("option", { name: /Inskickad text|Submitted text/ });
      expect(option !== null).toBe(offered);
      unmount();
    }
  });

  it("inserts custom form fields through the canonical flow_input namespace", async () => {
    const onInsert = vi.fn();

    render(VariablePicker, {
      steps: [],
      currentStepOrder: 1,
      formSchema: {
        fields: [{ name: "kundnamn", type: "text" }]
      },
      onInsert
    });

    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga från flödet|Insert from the flow)$/ })
    );
    await fireEvent.click(await screen.findByRole("option", { name: /kundnamn/ }));

    expect(onInsert).toHaveBeenCalledWith("{{flow_input.kundnamn}}");
  });

  it("offers the section number only on a step that reads section by section", async () => {
    const { unmount } = render(VariablePicker, {
      steps: [],
      currentStepOrder: 1,
      formSchema: undefined,
      sectionVariablesAvailable: true,
      onInsert: vi.fn()
    });
    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga från flödet|Insert from the flow)$/ })
    );
    expect(
      await screen.findByRole("option", { name: /Delens nummer|Section number/ })
    ).toBeTruthy();
    unmount();

    render(VariablePicker, {
      steps: [],
      currentStepOrder: 1,
      formSchema: { fields: [{ name: "kundnamn", type: "text" }] },
      onInsert: vi.fn()
    });
    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga från flödet|Insert from the flow)$/ })
    );
    await screen.findByRole("option", { name: /kundnamn/ });
    expect(screen.queryByRole("option", { name: /Delens nummer|Section number/ })).toBeNull();
  });

  // Kills: a tool argument is offered a step's whole output, or a structured
  // result no contract declares, which publish refuses; a reference publish
  // accepts is hidden from it; another use of the picker loses the whole output.
  it.each([
    {
      allowFor: undefined,
      extra: [
        ...["step_1.output", "step_2.output", "step_3.output", "step_4.output"],
        "step_3.output.structured"
      ]
    },
    { allowFor: "tool_argument" as const, extra: [] }
  ])("offers the references a value may take (allowFor $allowFor)", async ({ allowFor, extra }) => {
    const json = { output_type: "json" as const, user_description: "" };
    const contract = { type: "object", properties: { id: { type: "string" } } };
    render(VariablePicker, {
      steps: [
        flowStepFixture({ user_description: "Hämta" }),
        flowStepFixture({ ...json, step_order: 2, output_contract: contract }),
        flowStepFixture({ ...json, step_order: 3, output_contract: null }),
        flowStepFixture({ ...json, step_order: 4, output_contract: { type: "object" } })
      ],
      currentStepOrder: 5,
      formSchema: { fields: [{ name: "kundnamn", type: "text" }] },
      isAdvancedMode: true,
      transcriptionEnabled: true,
      allowFor,
      onInsert: vi.fn()
    });
    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga från flödet|Insert from the flow)$/ })
    );
    const offered = (await screen.findAllByRole("option")).map((option) =>
      option.querySelector("code")?.textContent?.slice(2, -2)
    );
    expect(offered.toSorted()).toEqual(
      [
        "flow_input.kundnamn",
        "transkribering",
        "föregående_steg",
        "Hämta",
        "step_1.output.text",
        "step_2.output.text",
        "step_2.output.structured.id",
        "step_3.output.text",
        "step_4.output.text",
        "step_4.output.structured",
        ...extra
      ].toSorted()
    );
  });
});
