import type { FlowLocale } from "./flowRunWizard";

export function getFlowStepUxCopy({
  locale,
  inputSource
}: {
  locale: FlowLocale;
  inputSource: string | null | undefined;
}) {
  const copy = FLOW_STEP_COPY[locale];

  return {
    instructionsTitle: copy.instructionsTitle,
    instructionsHelperTitle: copy.instructionsHelperTitle,
    instructionsHelperBody: copy.instructionsHelperBody,
    instructionsContrast: copy.instructionsContrast,
    instructionsPlaceholder: copy.instructionsPlaceholder,
    inputTemplateTitle: copy.inputTemplateTitle,
    inputTemplateEditorLabel: copy.inputTemplateTitle,
    inputTemplatePlaceholder: copy.inputTemplatePlaceholder,
    inputTemplateDescription: copy.inputTemplateDescription,
    inputTemplateCtaTitle: copy.inputTemplateCtaTitle,
    inputTemplateCtaAction: copy.inputTemplateCtaAction,
    inputTemplateDefaultHint: getDefaultHint(locale, inputSource)
  };
}

function getDefaultHint(locale: FlowLocale, inputSource: string | null | undefined): string {
  const copy = FLOW_STEP_COPY[locale];
  switch (inputSource) {
    case "previous_step":
      return copy.inputTemplateDefaultPreviousStep;
    case "all_previous_steps":
      return copy.inputTemplateDefaultAllPreviousSteps;
    case "flow_input":
      return copy.inputTemplateDefaultFlowInput;
    default:
      return copy.inputTemplateDefaultFallback;
  }
}

const FLOW_STEP_COPY = {
  sv: {
    instructionsTitle: "Instruktioner till AI:n",
    instructionsHelperTitle: "Beskriv hur AI:n ska arbeta i det här steget.",
    instructionsHelperBody: "Exempel: Svara kort och tydligt. Använd punktlista.",
    instructionsContrast:
      "Instruktioner styr hur AI:n arbetar. Underlag styr vilken text steget får.",
    instructionsPlaceholder: "t.ex. Svara kort och tydligt. Använd punktlista.",
    inputTemplateTitle: "Underlag till steget",
    inputTemplateDescription: "Här väljer du vilket underlag steget ska arbeta med.",
    inputTemplatePlaceholder: "t.ex. Använd bara titeln från steg 1 och rubriken från steg 2.",
    inputTemplateCtaTitle: "Anpassa underlaget (frivilligt)",
    inputTemplateCtaAction: "Anpassa underlaget",
    inputTemplateDefaultPreviousStep:
      "Om du lämnar detta tomt används resultatet från föregående steg.",
    inputTemplateDefaultAllPreviousSteps:
      "Om du lämnar detta tomt används resultat från tidigare steg.",
    inputTemplateDefaultFlowInput:
      "Om du lämnar detta tomt används texten som skickas in när flödet körs.",
    inputTemplateDefaultFallback: "Om du lämnar detta tomt används stegets vanliga underlag."
  },
  en: {
    instructionsTitle: "Instructions for the AI",
    instructionsHelperTitle: "Describe how the AI should work in this step.",
    instructionsHelperBody: "Example: Answer briefly and clearly. Use bullet points.",
    instructionsContrast:
      "Instructions control how the AI works. Material controls which text the step receives.",
    instructionsPlaceholder: "e.g. Answer briefly and clearly. Use bullet points.",
    inputTemplateTitle: "Material for the step",
    inputTemplateDescription: "Choose which material the step should work with.",
    inputTemplatePlaceholder: "e.g. Use only the title from step 1 and the heading from step 2.",
    inputTemplateCtaTitle: "Adjust the material (optional)",
    inputTemplateCtaAction: "Adjust the material",
    inputTemplateDefaultPreviousStep:
      "If you leave this empty, the result from the previous step will be used.",
    inputTemplateDefaultAllPreviousSteps:
      "If you leave this empty, results from earlier steps will be used.",
    inputTemplateDefaultFlowInput:
      "If you leave this empty, the text sent in when the flow runs will be used.",
    inputTemplateDefaultFallback:
      "If you leave this empty, the step's normal material will be used."
  }
} satisfies Record<FlowLocale, Record<string, string>>;
