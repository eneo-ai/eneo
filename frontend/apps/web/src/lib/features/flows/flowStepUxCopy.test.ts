import { describe, expect, it } from "vitest";

import { getFlowStepUxCopy } from "./flowStepUxCopy";

describe("flowStepUxCopy", () => {
  it("uses Underlag terminology and inline contrast copy in Swedish", () => {
    const copy = getFlowStepUxCopy({
      locale: "sv",
      inputSource: "previous_step"
    });

    expect(copy.inputTemplateTitle).toBe("Underlag till steget");
    expect(copy.inputTemplateEditorLabel).toBe("Underlag till steget");
    expect(copy.instructionsContrast).toBe(
      "Instruktioner styr hur AI:n arbetar. Underlag styr vilken text steget får."
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

    expect(copy.instructionsTitle).toBe("Instructions for the AI");
    expect(copy.inputTemplateTitle).toBe("Material for the step");
    expect(copy.inputTemplateDefaultHint).toBe(
      "If you leave this empty, the text sent in when the flow runs will be used."
    );
  });
});
