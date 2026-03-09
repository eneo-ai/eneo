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
  });

  it("keeps the matching material terminology in English for the same keys", () => {
    const messages = readMessages("en");

    expect(messages.flow_step_input_template).toBe("Material (advanced)");
    expect(messages.flow_step_input_template_user_title).toBe("Material for the step");
    expect(messages.flow_step_input_template_user_editor_label).toBe("Material for the step");
    expect(messages.flow_step_input_template_cta_title).toBe("Adjust the material (optional)");
    expect(messages.flow_step_input_template_desc).not.toContain("standard input");
  });
});
