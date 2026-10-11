import { m } from "$lib/paraglide/messages";
import { countMessage } from "./flowCount";

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
    | "recording-in-progress"
    | "local-recording-pending"
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
  hasTemplateOverview,
  hasFormFields,
  hasFreeformTextInput,
  stepsRequiringInput
}: {
  hasTemplateOverview: boolean;
  hasFormFields: boolean;
  hasFreeformTextInput: boolean;
  stepsRequiringInput: WizardStepInput[];
}): FlowRunWizardPage[] {
  const pages: FlowRunWizardPage[] = [];

  if (hasTemplateOverview) {
    pages.push({
      id: "overview",
      kind: "overview",
      title: m.flow_run_wizard_overview_title(),
      description: m.flow_run_wizard_overview_description(),
      stepOrder: null
    });
  }

  if (hasFormFields) {
    pages.push({
      id: "form",
      kind: "form",
      title: m.flow_run_wizard_form_title(),
      description: m.flow_run_wizard_form_description(),
      stepOrder: null
    });
  } else if (hasFreeformTextInput) {
    pages.push({
      id: "freeform",
      kind: "freeform",
      title: m.flow_run_wizard_freeform_title(),
      description: m.flow_run_wizard_freeform_description(),
      stepOrder: null
    });
  }

  for (const step of stepsRequiringInput) {
    pages.push({
      id: runtimeStepPageId(step.step_id),
      kind: "runtime-step",
      title: m.flow_run_wizard_runtime_step_title({ order: String(step.step_order) }),
      description: m.flow_run_wizard_runtime_step_description({ order: String(step.step_order) }),
      stepId: step.step_id,
      stepOrder: step.step_order,
      stepLabel: getStepLabel(step)
    });
  }

  pages.push({
    id: "review",
    kind: "review",
    title: m.flow_run_wizard_review_title(),
    description: m.flow_run_wizard_review_description(),
    stepOrder: null
  });

  return pages;
}

export function buildFlowRunBlockers({
  missingRequiredFieldNames,
  stepsRequiringInput,
  runtimeFilesByStepId,
  localRecordingStepIds = [],
  templateReadinessItems,
  uploadingStepIds,
  recordingStepIds
}: {
  missingRequiredFieldNames: string[];
  stepsRequiringInput: WizardStepInput[];
  runtimeFilesByStepId: Record<string, { id: string }[]>;
  localRecordingStepIds?: string[];
  templateReadinessItems: TemplateReadinessItem[];
  uploadingStepIds: string[];
  recordingStepIds?: string[];
}): FlowRunBlocker[] {
  const blockers: FlowRunBlocker[] = [];

  for (const fieldName of missingRequiredFieldNames) {
    blockers.push({
      id: `form:${fieldName}`,
      kind: "missing-form-field",
      pageId: "form",
      title: m.flow_run_wizard_missing_form_field({ name: fieldName }),
      actionLabel: m.flow_run_wizard_go_to_form(),
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
        title: m.flow_run_wizard_missing_runtime_input(stepWords(step)),
        actionLabel: m.flow_run_wizard_go_to_step({ order: String(step.step_order) }),
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
      title: m.flow_run_wizard_upload_in_progress(stepWords(step)),
      actionLabel: m.flow_run_wizard_go_to_step({ order: String(step.step_order) }),
      blocksProgress: false
    });
  }

  for (const stepId of recordingStepIds ?? []) {
    const step = stepsRequiringInput.find((item) => item.step_id === stepId);
    if (!step) continue;
    blockers.push({
      id: `recording:${stepId}`,
      kind: "recording-in-progress",
      pageId: runtimeStepPageId(stepId),
      title: m.flow_run_wizard_recording_in_progress(stepWords(step)),
      actionLabel: m.flow_run_wizard_go_to_step({ order: String(step.step_order) }),
      blocksProgress: true
    });
  }

  for (const stepId of localRecordingStepIds) {
    const step = stepsRequiringInput.find((item) => item.step_id === stepId);
    if (!step) continue;
    blockers.push({
      id: `local-recording:${stepId}`,
      kind: "local-recording-pending",
      pageId: runtimeStepPageId(stepId),
      title: m.flow_run_wizard_local_recording_pending(stepWords(step)),
      actionLabel: m.flow_run_wizard_go_to_step({ order: String(step.step_order) }),
      blocksProgress: true
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
      title: item.template_name
        ? m.flow_run_wizard_template_not_ready({ name: item.template_name })
        : m.flow_run_wizard_template_not_ready_unnamed(),
      actionLabel: m.flow_run_wizard_go_to_overview(),
      blocksProgress: false
    });
  }

  return blockers;
}

export function runtimeStepPageId(stepId: string): `runtime-step:${string}` {
  return `runtime-step:${stepId}`;
}

export function buildFlowRunReviewSummary({
  templateCount,
  filledFieldCount,
  runtimeStepCountWithFiles,
  uploadedFileCount
}: {
  templateCount: number;
  filledFieldCount: number;
  runtimeStepCountWithFiles: number;
  uploadedFileCount: number;
}): FlowRunReviewSummaryItem[] {
  const items: FlowRunReviewSummaryItem[] = [];

  if (templateCount > 0) {
    items.push({
      id: "templates",
      label: countMessage(
        templateCount,
        m.flow_run_wizard_summary_templates_one,
        m.flow_run_wizard_summary_templates
      )
    });
  }
  if (filledFieldCount > 0) {
    items.push({
      id: "fields",
      label: countMessage(
        filledFieldCount,
        m.flow_run_wizard_summary_fields_one,
        m.flow_run_wizard_summary_fields
      )
    });
  }
  if (runtimeStepCountWithFiles > 0) {
    items.push({
      id: "steps",
      label: countMessage(
        runtimeStepCountWithFiles,
        m.flow_run_wizard_summary_steps_one,
        m.flow_run_wizard_summary_steps
      )
    });
  }
  if (uploadedFileCount > 0) {
    items.push({
      id: "files",
      label: countMessage(
        uploadedFileCount,
        m.flow_run_wizard_summary_files_one,
        m.flow_run_wizard_summary_files
      )
    });
  }

  return items;
}

function getStepLabel(step: WizardStepInput): string {
  return step.label?.trim() || m.flow_step_fallback_label({ order: String(step.step_order) });
}

function stepWords(step: WizardStepInput): { order: string; label: string } {
  return { order: String(step.step_order), label: getStepLabel(step) };
}
