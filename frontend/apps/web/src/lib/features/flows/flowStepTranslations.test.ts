import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

function readMessages(locale: "sv" | "en") {
  const filePath = path.resolve(process.cwd(), `messages/${locale}.json`);
  return JSON.parse(readFileSync(filePath, "utf-8")) as Record<string, string>;
}

describe("flow step translation copy", () => {
  it("uses Underlag language in Swedish for the editor-facing flow step keys", () => {
    const messages = readMessages("sv");

    expect(messages.flow_step_input_template).toBe("Underlag (avancerat)");
    expect(messages.flow_step_input_template_user_title).toBe("Underlag till steget");
    expect(messages.flow_step_input_template_user_editor_label).toBe("Underlag till steget");
    expect(messages.flow_step_input_template_cta_title).toBe("Anpassa underlaget (frivilligt)");
    expect(messages.flow_step_input_template_desc).not.toContain("standardindatan");
    expect(messages.flow_step_input_template_cta_desc).not.toContain("indatamall");
    expect(messages.flow_step_summary_source_input_template).not.toContain("Standardindatan");
    expect(messages.flow_step_instructions_compare_title).toBe("Hur AI:n ska arbeta");
    expect(messages.flow_step_instructions_compare_body).toBe(
      'Exempel: "Sammanfatta i tre punkter på svenska". Här styr du uppgift, ton och svarsformat.'
    );
    expect(messages.flow_step_input_template_compare_title).toBe("Vilken text AI:n får");
    expect(messages.flow_step_input_template_compare_body).toBe(
      'Exempel: "Rubrik: titel". Här bygger du texten AI:n faktiskt ska arbeta med.'
    );
    expect(messages.flow_step_instructions_tooltip).toBe(
      'Styr uppdraget: vad AI:n ska göra och hur den ska svara. Exempel: "Sammanfatta i tre punkter på svenska". Variabler fungerar här, men blir en del av instruktionen, inte av texten AI:n bearbetar.'
    );
    expect(messages.flow_step_input_template_tooltip).toBe(
      'Styr vilken text AI:n faktiskt får in. Lämna tomt om steget ska använda sitt vanliga underlag. Samma variabler som i Instruktioner fungerar här, men här bygger du texten AI:n ska bearbeta, t.ex. med titel eller step_1.output.text.'
    );
    expect(messages.flow_step_input_template_tooltip).toContain("step_1.output.text");
  });

  it("keeps the matching material terminology in English for the same keys", () => {
    const messages = readMessages("en");

    expect(messages.flow_step_input_template).toBe("Material (advanced)");
    expect(messages.flow_step_input_template_user_title).toBe("Material for the step");
    expect(messages.flow_step_input_template_user_editor_label).toBe("Material for the step");
    expect(messages.flow_step_input_template_cta_title).toBe("Adjust the material (optional)");
    expect(messages.flow_step_input_template_desc).not.toContain("standard input");
    expect(messages.flow_step_instructions_compare_title).toBe("How the AI should work");
    expect(messages.flow_step_instructions_compare_body).toBe(
      'Example: "Summarize in three bullets in Swedish". Use this for the task, tone, and response format.'
    );
    expect(messages.flow_step_input_template_compare_title).toBe("What text the AI receives");
    expect(messages.flow_step_input_template_compare_body).toBe(
      'Example: "Title: title". Use this to build the actual text the AI should work with.'
    );
    expect(messages.flow_step_instructions_tooltip).toBe(
      'Controls the task: what the AI should do and how it should respond. Example: "Summarize in three bullets in Swedish". Variables work here, but they become part of the instruction, not the text the AI processes.'
    );
    expect(messages.flow_step_input_template_tooltip).toBe(
      'Controls which text the AI actually receives. Leave this empty if the step should use its normal material. The same variables work here as in Instructions, but here you build the text the AI will process, e.g. with title or step_1.output.text.'
    );
    expect(messages.flow_step_input_template_tooltip).toContain("step_1.output.text");
  });
});
