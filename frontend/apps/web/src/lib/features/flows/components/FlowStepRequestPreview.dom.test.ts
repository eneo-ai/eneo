import { cleanup, render, screen, within } from "@testing-library/svelte";
import type { FlowStep } from "@eneo/eneo-js";
import { afterAll, afterEach, describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";

import FlowStepRequestPreview from "./FlowStepRequestPreview.svelte";

afterEach(() => {
  cleanup();
});

// Bits UI releases the dialog's body scroll lock 24 ms after it closes
// (body-scroll-lock.svelte.js). Waiting past that before the file ends lets
// the timer fire here instead of after jsdom is gone, where it throws
// "document is not defined" into whichever file runs next.
afterAll(async () => {
  await new Promise((resolve) => setTimeout(resolve, 50));
});

const step = {
  step_order: 1,
  user_description: "Fördela uppgifter",
  output_type: "json",
  input_config: { text_processing: { mode: "process_each_section" } },
  output_contract: {
    type: "object",
    properties: {
      poster: {
        type: "array",
        items: {
          type: "object",
          properties: {
            grunduppgifter: { type: "string" },
            stod_i_vardagen: { type: "string", description: "Vilket stöd som behövs" }
          }
        }
      }
    }
  }
} as unknown as FlowStep;

function renderPreview(isAdvancedMode = false, overrides: Record<string, unknown> = {}) {
  render(FlowStepRequestPreview, {
    props: {
      open: true,
      step,
      steps: [step],
      formSchema: { fields: [{ name: "namn", label: "Brukarens namn", type: "text" }] },
      instructionText: "Läs {{step_input.text}} för {{flow_input.namn}}.",
      ownText: "",
      materialSentence: "AI:n läser det som laddas upp när flödet körs.",
      hasAttachments: false,
      hasKnowledge: false,
      isAdvancedMode,
      transcriptionEnabled: false,
      ...overrides
    }
  });
  return screen.getByRole("dialog", { name: m.flow_request_preview_title() });
}

describe("FlowStepRequestPreview", () => {
  it("shows the instruction with variables named in words", () => {
    const dialog = renderPreview();
    const heading = within(dialog).getByRole("heading", {
      name: m.flow_request_preview_instruction()
    });
    expect(heading.nextElementSibling?.textContent).toBe(
      `Läs ${m.flow_variable_upload_label()} för Brukarens namn.`
    );
    expect(dialog.textContent).not.toContain("{{");
    expect(within(dialog).getByText("AI:n läser det som laddas upp när flödet körs.")).toBeTruthy();
  });

  it("lists the item fields of a section-by-section answer", () => {
    const dialog = renderPreview();
    expect(within(dialog).getByText(m.flow_request_preview_answer_per_section())).toBeTruthy();
    const items = within(dialog)
      .getAllByRole("listitem")
      .map((item) => item.textContent?.replace(/\s+/g, " ").trim());
    expect(items).toEqual(["Grunduppgifter", "Stod i vardagen Vilket stöd som behövs"]);
    expect(within(dialog).queryByText("stod_i_vardagen")).toBeNull();
  });

  it("keeps the material sentence above the own text and names added files and knowledge", () => {
    const dialog = renderPreview(false, {
      ownText: "Underlag: {{flow_input.namn}}",
      materialSentence: "AI:n läser din egen text nedan och resultaten du har valt.",
      hasAttachments: true,
      hasKnowledge: true
    });
    const heading = within(dialog).getByRole("heading", {
      name: m.flow_request_preview_material()
    });
    const lines = [...(heading.parentElement?.children ?? [])]
      .slice(1)
      .map((element) => element.textContent?.trim());
    expect(lines).toEqual([
      "AI:n läser din egen text nedan och resultaten du har valt.",
      "Underlag: Brukarens namn",
      m.flow_request_preview_material_files(),
      m.flow_request_preview_material_knowledge()
    ]);
  });

  it("shows the raw field names in advanced mode", () => {
    const dialog = renderPreview(true);
    expect(within(dialog).getByText("stod_i_vardagen")).toBeTruthy();
  });
});
