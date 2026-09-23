import type { FlowLocale } from "./flowRunWizard";

// The placeholders carry `{{ }}` examples, which Paraglide would read as
// message parameters; that is why this copy lives here and not in the catalog.
export function getFlowStepUxCopy({ locale }: { locale: FlowLocale }) {
  const copy = FLOW_STEP_COPY[locale];

  return {
    instructionsTitle: copy.instructionsTitle,
    instructionsHelperTitle: copy.instructionsHelperTitle,
    instructionsHelperBody: copy.instructionsHelperBody,
    instructionsPlaceholder: copy.instructionsPlaceholder,
    inputTemplatePlaceholder: copy.inputTemplatePlaceholder
  };
}

export type FlowStepUxCopy = ReturnType<typeof getFlowStepUxCopy>;

const FLOW_STEP_COPY = {
  sv: {
    instructionsTitle: "Instruktion till AI:n",
    instructionsHelperTitle: "Beskriv hur AI:n ska arbeta i det här steget.",
    instructionsHelperBody: "Exempel: Svara kort och tydligt. Använd punktlista.",
    instructionsPlaceholder: "t.ex. Svara kort och tydligt. Använd punktlista.",
    inputTemplatePlaceholder:
      "t.ex.\nÄrende: {{ärendenummer}}\nSammanfattning: {{Sammanfatta ärendet}}"
  },
  en: {
    instructionsTitle: "Instruction for the AI",
    instructionsHelperTitle: "Describe how the AI should work in this step.",
    instructionsHelperBody: "Example: Answer briefly and clearly. Use bullet points.",
    instructionsPlaceholder: "e.g. Answer briefly and clearly. Use bullet points.",
    inputTemplatePlaceholder: "e.g.\nCase: {{case_number}}\nSummary: {{Summarize the case}}"
  }
} satisfies Record<FlowLocale, Record<string, string>>;
