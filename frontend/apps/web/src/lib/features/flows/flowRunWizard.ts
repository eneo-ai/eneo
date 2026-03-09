export type FlowLocale = "sv" | "en";

type WizardStepInput = {
  step_id: string;
  step_order: number;
  label?: string | null;
  required: boolean;
  input_format: string;
  accepted_mimetypes: string[];
};

type TemplateReadinessItem = {
  step_id: string;
  status?: string | null;
  template_name?: string | null;
  message_code?: string | null;
};

export type FlowRunWizardPage =
  | {
      id: "overview";
      kind: "overview";
      title: string;
      description: string;
      stepOrder: null;
    }
  | {
      id: "form";
      kind: "form";
      title: string;
      description: string;
      stepOrder: null;
    }
  | {
      id: "freeform";
      kind: "freeform";
      title: string;
      description: string;
      stepOrder: null;
    }
  | {
      id: `runtime-step:${string}`;
      kind: "runtime-step";
      title: string;
      description: string;
      stepId: string;
      stepOrder: number;
      stepLabel: string;
    }
  | {
      id: "review";
      kind: "review";
      title: string;
      description: string;
      stepOrder: null;
    };

export type FlowRunBlocker = {
  id: string;
  kind:
    | "missing-form-field"
    | "missing-runtime-input"
    | "upload-in-progress"
    | "template-readiness";
  pageId: FlowRunWizardPage["id"];
  title: string;
  actionLabel: string;
  blocksProgress: boolean;
};

export type FlowRunReviewSummaryItem = {
  id: "templates" | "fields" | "steps" | "files";
  label: string;
};

export function buildFlowRunWizardPages({
  locale,
  hasTemplateOverview,
  hasFormFields,
  hasFreeformTextInput,
  stepsRequiringInput
}: {
  locale: FlowLocale;
  hasTemplateOverview: boolean;
  hasFormFields: boolean;
  hasFreeformTextInput: boolean;
  stepsRequiringInput: WizardStepInput[];
}): FlowRunWizardPage[] {
  const copy = RUN_WIZARD_COPY[locale];
  const pages: FlowRunWizardPage[] = [];

  if (hasTemplateOverview) {
    pages.push({
      id: "overview",
      kind: "overview",
      title: copy.overviewTitle,
      description: copy.overviewDescription,
      stepOrder: null
    });
  }

  if (hasFormFields) {
    pages.push({
      id: "form",
      kind: "form",
      title: copy.formTitle,
      description: copy.formDescription,
      stepOrder: null
    });
  } else if (hasFreeformTextInput) {
    pages.push({
      id: "freeform",
      kind: "freeform",
      title: copy.freeformTitle,
      description: copy.freeformDescription,
      stepOrder: null
    });
  }

  for (const step of stepsRequiringInput) {
    pages.push({
      id: runtimeStepPageId(step.step_id),
      kind: "runtime-step",
      title: copy.runtimeStepTitle(step.step_order),
      description: copy.runtimeStepDescription(step.step_order),
      stepId: step.step_id,
      stepOrder: step.step_order,
      stepLabel: getStepLabel(step)
    });
  }

  pages.push({
    id: "review",
    kind: "review",
    title: copy.reviewTitle,
    description: copy.reviewDescription,
    stepOrder: null
  });

  return pages;
}

export function buildFlowRunBlockers({
  locale,
  missingRequiredFieldNames,
  stepsRequiringInput,
  runtimeFilesByStepId,
  templateReadinessItems,
  uploadingStepIds
}: {
  locale: FlowLocale;
  missingRequiredFieldNames: string[];
  stepsRequiringInput: WizardStepInput[];
  runtimeFilesByStepId: Record<string, { id: string }[]>;
  templateReadinessItems: TemplateReadinessItem[];
  uploadingStepIds: string[];
}): FlowRunBlocker[] {
  const copy = RUN_WIZARD_COPY[locale];
  const blockers: FlowRunBlocker[] = [];

  for (const fieldName of missingRequiredFieldNames) {
    blockers.push({
      id: `form:${fieldName}`,
      kind: "missing-form-field",
      pageId: "form",
      title: copy.missingFormField(fieldName),
      actionLabel: copy.goToForm,
      blocksProgress: true
    });
  }

  for (const step of stepsRequiringInput) {
    const files = runtimeFilesByStepId[step.step_id] ?? [];
    if (step.required && files.length === 0) {
      blockers.push({
        id: runtimeStepPageId(step.step_id),
        kind: "missing-runtime-input",
        pageId: runtimeStepPageId(step.step_id),
        title: copy.missingRuntimeInput(step.step_order, getStepLabel(step)),
        actionLabel: copy.goToStep(step.step_order),
        blocksProgress: true
      });
    }
  }

  for (const stepId of uploadingStepIds) {
    const step = stepsRequiringInput.find((item) => item.step_id === stepId);
    if (!step) continue;
    blockers.push({
      id: `uploading:${stepId}`,
      kind: "upload-in-progress",
      pageId: runtimeStepPageId(stepId),
      title: copy.uploadInProgress(step.step_order, getStepLabel(step)),
      actionLabel: copy.goToStep(step.step_order),
      blocksProgress: false
    });
  }

  for (const item of templateReadinessItems) {
    if (item.status !== "needs_action" && item.status !== "unavailable") {
      continue;
    }
    blockers.push({
      id: `template:${item.step_id}`,
      kind: "template-readiness",
      pageId: "overview",
      title: copy.templateNotReady(item.template_name ?? item.step_id),
      actionLabel: copy.goToOverview,
      blocksProgress: false
    });
  }

  return blockers;
}

export function runtimeStepPageId(stepId: string): `runtime-step:${string}` {
  return `runtime-step:${stepId}`;
}

export function buildFlowRunReviewSummary({
  locale,
  templateCount,
  filledFieldCount,
  runtimeStepCountWithFiles,
  uploadedFileCount
}: {
  locale: FlowLocale;
  templateCount: number;
  filledFieldCount: number;
  runtimeStepCountWithFiles: number;
  uploadedFileCount: number;
}): FlowRunReviewSummaryItem[] {
  const copy = RUN_WIZARD_COPY[locale];
  const items: FlowRunReviewSummaryItem[] = [];

  if (templateCount > 0) {
    items.push({
      id: "templates",
      label: copy.reviewTemplateSummary(templateCount)
    });
  }
  if (filledFieldCount > 0) {
    items.push({
      id: "fields",
      label: copy.reviewFieldSummary(filledFieldCount)
    });
  }
  if (runtimeStepCountWithFiles > 0) {
    items.push({
      id: "steps",
      label: copy.reviewStepSummary(runtimeStepCountWithFiles)
    });
  }
  if (uploadedFileCount > 0) {
    items.push({
      id: "files",
      label: copy.reviewFileSummary(uploadedFileCount)
    });
  }

  return items;
}

function getStepLabel(step: WizardStepInput): string {
  return step.label?.trim() || `Step ${step.step_order}`;
}

const RUN_WIZARD_COPY = {
  sv: {
    overviewTitle: "Översikt",
    overviewDescription:
      "Kontrollera mallstatus och vad som behöver vara klart innan du kör flödet.",
    formTitle: "Formulär",
    formDescription: "Fyll i de uppgifter som ska användas i flödet.",
    freeformTitle: "Indata",
    freeformDescription: "Skriv den text som ska skickas in när flödet körs.",
    reviewTitle: "Granska och kör",
    reviewDescription: "Kontrollera underlag och eventuella hinder innan du startar flödet.",
    runtimeStepTitle: (stepOrder: number) => `Steg ${stepOrder} i flödet`,
    runtimeStepDescription: (stepOrder: number) =>
      `Detta underlag används bara i steg ${stepOrder}.`,
    missingFormField: (fieldName: string) => `Fältet "${fieldName}" behöver fyllas i.`,
    missingRuntimeInput: (stepOrder: number, stepLabel: string) =>
      `Ladda upp filer för steg ${stepOrder}: ${stepLabel}.`,
    uploadInProgress: (stepOrder: number, stepLabel: string) =>
      `Filer laddas fortfarande upp för steg ${stepOrder}: ${stepLabel}.`,
    templateNotReady: (templateName: string) =>
      `Mallen "${templateName}" behöver åtgärdas innan flödet kan köras.`,
    reviewTemplateSummary: (count: number) => `${count} mall${count === 1 ? "" : "ar"} klar`,
    reviewFieldSummary: (count: number) => `${count} fält ifyllda`,
    reviewStepSummary: (count: number) => `${count} steg med uppladdat underlag`,
    reviewFileSummary: (count: number) => `${count} fil${count === 1 ? "" : "er"} uppladdade`,
    goToForm: "Gå till formulär",
    goToStep: (stepOrder: number) => `Gå till steg ${stepOrder}`,
    goToOverview: "Gå till översikt"
  },
  en: {
    overviewTitle: "Overview",
    overviewDescription: "Check template status and what must be ready before you run the flow.",
    formTitle: "Form",
    formDescription: "Fill in the information that should be used in the flow.",
    freeformTitle: "Input",
    freeformDescription: "Write the text that should be sent when the flow runs.",
    reviewTitle: "Review and run",
    reviewDescription: "Review the material and any blockers before you start the flow.",
    runtimeStepTitle: (stepOrder: number) => `Step ${stepOrder} in the flow`,
    runtimeStepDescription: (stepOrder: number) =>
      `This material is only used in step ${stepOrder}.`,
    missingFormField: (fieldName: string) => `The field "${fieldName}" needs to be filled in.`,
    missingRuntimeInput: (stepOrder: number, stepLabel: string) =>
      `Upload files for step ${stepOrder}: ${stepLabel}.`,
    uploadInProgress: (stepOrder: number, stepLabel: string) =>
      `Files are still uploading for step ${stepOrder}: ${stepLabel}.`,
    templateNotReady: (templateName: string) =>
      `The template "${templateName}" needs attention before the flow can run.`,
    reviewTemplateSummary: (count: number) => `${count} template${count === 1 ? "" : "s"} ready`,
    reviewFieldSummary: (count: number) => `${count} fields completed`,
    reviewStepSummary: (count: number) => `${count} steps with uploaded material`,
    reviewFileSummary: (count: number) => `${count} file${count === 1 ? "" : "s"} uploaded`,
    goToForm: "Go to form",
    goToStep: (stepOrder: number) => `Go to step ${stepOrder}`,
    goToOverview: "Go to overview"
  }
} satisfies Record<FlowLocale, Record<string, unknown>>;
