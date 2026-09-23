import { describe, expect, it } from "vitest";

import { getFlowStepUxCopy } from "./flowStepUxCopy";

describe("flowStepUxCopy", () => {
  it("uses Underlag terminology and template-focused copy in Swedish", () => {
    const copy = getFlowStepUxCopy({
      locale: "sv",
      inputSource: "previous_step"
    });

    expect(copy.inputTemplateTitle).toBe("Anpassad text till AI:n");
    expect(copy.inputTemplateEditorLabel).toBe("Anpassad text till AI:n");
    expect(copy.inputTemplateCtaAction).toBe("Anpassa texten");
    expect(copy.inputTemplateDescription).toBe(
      "Bestäm exakt vilken text AI:n får att arbeta med. Skriv egna rubriker och lägg in formulärfält eller svar från tidigare steg med Infoga variabel."
    );
    expect(copy.inputTemplatePlaceholder).toBe(
      "t.ex.\nÄrende: {{ärendenummer}}\nSammanfattning: {{Sammanfatta ärendet}}"
    );
  });

  it("explains default underlag differently depending on the input source", () => {
    expect(
      getFlowStepUxCopy({ locale: "sv", inputSource: "previous_step" }).inputTemplateDefaultHint
    ).toBe("Om du lämnar detta tomt används resultatet från föregående steg.");
    expect(
      getFlowStepUxCopy({ locale: "sv", inputSource: "all_previous_steps" })
        .inputTemplateDefaultHint
    ).toBe("Om du lämnar detta tomt används resultat från tidigare steg.");
    expect(
      getFlowStepUxCopy({ locale: "sv", inputSource: "flow_input" }).inputTemplateDefaultHint
    ).toBe("Om du lämnar detta tomt används texten som skickas in när flödet körs.");
  });

  it("keeps the same mental model in English", () => {
    const copy = getFlowStepUxCopy({
      locale: "en",
      inputSource: "flow_input"
    });

    expect(copy.instructionsTitle).toBe("Instruction for the AI");
    expect(copy.inputTemplateTitle).toBe("Custom text for the AI");
    expect(copy.inputTemplateEditorLabel).toBe("Custom text for the AI");
    expect(copy.inputTemplateCtaAction).toBe("Customize text");
    expect(copy.inputTemplateDescription).toBe(
      "Decide exactly which text the AI gets to work with. Write your own headings and insert form fields or answers from earlier steps with Insert variable."
    );
    expect(copy.inputTemplatePlaceholder).toBe(
      "e.g.\nCase: {{case_number}}\nSummary: {{Summarize the case}}"
    );
    expect(copy.inputTemplateDefaultHint).toBe(
      "If you leave this empty, the text sent in when the flow runs will be used."
    );
  });
});
