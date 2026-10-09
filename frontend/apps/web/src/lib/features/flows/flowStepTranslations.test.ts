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

    expect(messages.flow_step_summary_source_input_template).not.toContain("Standardindatan");
    expect(messages.flow_step_instructions_tooltip).toBe(
      "Styr uppdraget: vad AI:n ska göra och hur den ska svara. Exempel: ”Sammanfatta i tre punkter på svenska”. Det du infogar från flödet blir en del av instruktionen, inte av texten AI:n bearbetar."
    );
    expect(messages.flow_runtime_input_title).toBe("Filer vid körning");
    expect(messages.flow_runtime_input_description).toBe(
      "Filer som laddas upp när flödet körs blir tillgängliga i det här steget."
    );
    expect(messages.flow_runtime_input_required).toBe("Kräv filuppladdning");
    expect(messages.flow_step_security_inherit).toBe("Ärvs automatiskt");
  });

  it("keeps the matching material terminology in English for the same keys", () => {
    const messages = readMessages("en");

    expect(messages.flow_step_instructions_tooltip).toBe(
      "Controls the task: what the AI should do and how it should respond. Example: “Summarize in three bullets in Swedish”. Anything you insert from the flow becomes part of the instruction, not of the text the AI processes."
    );
    expect(messages.flow_runtime_input_title).toBe("Files at run time");
    expect(messages.flow_runtime_input_description).toBe(
      "Files uploaded when the flow runs become available to this step."
    );
    expect(messages.flow_runtime_input_required).toBe("Require a file upload");
    expect(messages.flow_step_security_inherit).toBe("Inherited automatically");
  });
});
