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

export type FlowStepUxCopy = ReturnType<typeof getFlowStepUxCopy>;

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
    instructionsTitle: "Instruktion till AI:n",
    instructionsHelperTitle: "Beskriv hur AI:n ska arbeta i det här steget.",
    instructionsHelperBody: "Exempel: Svara kort och tydligt. Använd punktlista.",
    instructionsPlaceholder: "t.ex. Svara kort och tydligt. Använd punktlista.",
    inputTemplateTitle: "Anpassad text till AI:n",
    inputTemplateDescription:
      "Bestäm exakt vilken text AI:n får att arbeta med. Skriv egna rubriker och lägg in formulärfält eller svar från tidigare steg med Infoga variabel.",
    inputTemplatePlaceholder:
      "t.ex.\nÄrende: {{ärendenummer}}\nSammanfattning: {{Sammanfatta ärendet}}",
    inputTemplateCtaTitle: "Anpassa underlaget",
    inputTemplateCtaAction: "Anpassa texten",
    inputTemplateDefaultPreviousStep:
      "Om du lämnar detta tomt används resultatet från föregående steg.",
    inputTemplateDefaultAllPreviousSteps:
      "Om du lämnar detta tomt används resultat från tidigare steg.",
    inputTemplateDefaultFlowInput:
      "Om du lämnar detta tomt används texten som skickas in när flödet körs.",
    inputTemplateDefaultFallback: "Om du lämnar detta tomt används stegets vanliga underlag."
  },
  en: {
    instructionsTitle: "Instruction for the AI",
    instructionsHelperTitle: "Describe how the AI should work in this step.",
    instructionsHelperBody: "Example: Answer briefly and clearly. Use bullet points.",
    instructionsPlaceholder: "e.g. Answer briefly and clearly. Use bullet points.",
    inputTemplateTitle: "Custom text for the AI",
    inputTemplateDescription:
      "Decide exactly which text the AI gets to work with. Write your own headings and insert form fields or answers from earlier steps with Insert variable.",
    inputTemplatePlaceholder: "e.g.\nCase: {{case_number}}\nSummary: {{Summarize the case}}",
    inputTemplateCtaTitle: "Customize material",
    inputTemplateCtaAction: "Customize text",
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
