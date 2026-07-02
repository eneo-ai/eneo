import { m } from "$lib/paraglide/messages";
import type { FlowStep } from "@eneo/eneo-js";
import type { FlowStepValidationIssue } from "$lib/features/flows/flowStepTypes";
import type {
  FlowSourceHintKind,
  FlowOutputHintKind
} from "$lib/features/flows/flowStepPresentation";
import { hasAdvancedOutputConfig } from "$lib/features/flows/flowCitationMode";

// ---------------------------------------------------------------------------
// Label arrays & lookup maps
// ---------------------------------------------------------------------------

export const INPUT_SOURCE_LABELS: Record<string, () => string> = {
  flow_input: () => m.flow_input_source_flow_input(),
  previous_step: () => m.flow_input_source_previous_step(),
  all_previous_steps: () => m.flow_input_source_all_previous_steps(),
  http_get: () => m.flow_input_source_http_get(),
  http_post: () => m.flow_input_source_http_post()
};

export const INPUT_TYPES = [
  {
    value: "text",
    get label() {
      return m.flow_type_text();
    }
  },
  {
    value: "json",
    get label() {
      return m.flow_type_json();
    }
  },
  {
    value: "document",
    get label() {
      return m.flow_type_document();
    }
  },
  {
    value: "file",
    get label() {
      return m.flow_type_file();
    }
  },
  {
    value: "image",
    get label() {
      return m.flow_type_image();
    }
  },
  {
    value: "audio",
    get label() {
      return m.flow_type_audio();
    }
  },
  {
    value: "any",
    get label() {
      return m.flow_type_any();
    }
  }
];

export const OUTPUT_TYPES = [
  {
    value: "text",
    get label() {
      return m.flow_output_type_text();
    }
  },
  {
    value: "json",
    get label() {
      return m.flow_output_type_json();
    }
  },
  {
    value: "pdf",
    get label() {
      return m.flow_output_type_pdf();
    }
  },
  {
    value: "docx",
    get label() {
      return m.flow_output_type_docx();
    }
  }
];

export const OUTPUT_MODES = [
  {
    value: "pass_through",
    get label() {
      return m.flow_output_mode_pass_through();
    }
  },
  {
    value: "transcribe_only",
    get label() {
      return m.flow_output_mode_transcribe_only();
    }
  },
  {
    value: "http_post",
    get label() {
      return m.flow_output_mode_http_post();
    }
  },
  {
    value: "template_fill",
    get label() {
      return m.flow_output_mode_template_fill();
    }
  }
];

// ---------------------------------------------------------------------------
// Label lookups
// ---------------------------------------------------------------------------

export function getInputTypeLabel(value: string): string {
  return INPUT_TYPES.find((type) => type.value === value)?.label ?? value;
}

export function getInputSourceLabel(value: string): string {
  return INPUT_SOURCE_LABELS[value]?.() ?? value;
}

export function getOutputTypeLabel(value: string): string {
  return OUTPUT_TYPES.find((type) => type.value === value)?.label ?? value;
}

export function getInputSourceOptionLabel(value: string, legacyInvalid: boolean): string {
  const label = getInputSourceLabel(value);
  return legacyInvalid ? `${label} (${m.flow_step_legacy_invalid_option()})` : label;
}

export function getInputTypeOptionLabel(value: string, legacyInvalid: boolean): string {
  const label = getInputTypeLabel(value);
  return legacyInvalid ? `${label} (${m.flow_step_legacy_invalid_option()})` : label;
}

// ---------------------------------------------------------------------------
// Hint text helpers
// ---------------------------------------------------------------------------

export function getSourceHintText(sourceHintKind: FlowSourceHintKind | null): string {
  switch (sourceHintKind) {
    case "flow_input":
      return m.flow_step_source_help_flow_input();
    case "previous_step_json":
      return m.flow_step_source_help_previous_json();
    case "previous_step_document_text":
      return m.flow_step_source_help_previous_document();
    case "all_previous_steps":
      return m.flow_step_source_help_all_previous_steps();
    case "http_source":
      return m.flow_step_source_help_http();
    case "previous_step_text":
    default:
      return m.flow_step_source_help_previous_text();
  }
}

export function getInputFormatHintText(
  sourceHintKind: FlowSourceHintKind | null,
  inputType?: string
): string | null {
  if (sourceHintKind === "previous_step_json") {
    return inputType === "json"
      ? m.flow_step_input_format_help_json_selected()
      : m.flow_step_input_format_help_text_selected();
  }
  if (sourceHintKind === "previous_step_document_text") {
    return m.flow_step_input_format_help_document_text();
  }
  if (sourceHintKind === "all_previous_steps") {
    return m.flow_step_input_format_help_all_previous_steps();
  }
  return null;
}

export function getOutputHintText(
  outputMode: string | undefined,
  outputHintKind: FlowOutputHintKind | null
): string | null {
  if (outputMode === "template_fill") {
    return m.flow_template_fill_summary();
  }
  switch (outputHintKind) {
    case "structured_json":
      return m.flow_step_output_format_help_json();
    case "document_artifact":
      return m.flow_step_output_format_help_document();
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Step analysis
// ---------------------------------------------------------------------------

export function hasAdvancedSettingsActive(
  step: FlowStep,
  hasInputTemplateOverride: boolean
): boolean {
  return Boolean(
    step.output_mode === "template_fill" ||
    step.input_type === "any" ||
    step.input_type === "file" ||
    step.input_contract ||
    step.output_contract ||
    step.input_config ||
    hasAdvancedOutputConfig(step) ||
    hasInputTemplateOverride
  );
}

// ---------------------------------------------------------------------------
// MIME presets (for runtime input config UI)
// ---------------------------------------------------------------------------

export type MimePreset = { mime: string; label: string };

export const MIME_PRESETS_DOCUMENT: MimePreset[] = [
  { mime: "application/pdf", label: "PDF" },
  {
    mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    label: "Word (.docx)"
  },
  {
    mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    label: "Excel (.xlsx)"
  },
  { mime: "application/vnd.ms-excel", label: "Excel (.xls)" },
  {
    mime: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    label: "PowerPoint (.pptx)"
  },
  { mime: "text/csv", label: "CSV" },
  { mime: "text/plain", label: "Text" },
  { mime: "text/markdown", label: "Markdown" }
];

export const MIME_PRESETS_AUDIO: MimePreset[] = [
  { mime: "audio/mpeg", label: "MP3" },
  { mime: "audio/wav", label: "WAV" },
  { mime: "audio/ogg", label: "OGG" },
  { mime: "audio/x-m4a", label: "M4A" },
  { mime: "audio/webm", label: "WebM" },
  { mime: "audio/mp4", label: "MP4 (ljud)" }
];

export function getMimePresetsForFormat(format: string): MimePreset[] {
  if (format === "audio") return MIME_PRESETS_AUDIO;
  return MIME_PRESETS_DOCUMENT;
}

export function parseMimeOverrideDraft(rawValue: string): string[] {
  return rawValue
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

// ---------------------------------------------------------------------------
// Template fill display helpers
// ---------------------------------------------------------------------------

export function getTemplateAssetStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "ready":
      return "Ready";
    case "needs_action":
      return "Needs action";
    case "read_only":
      return "Read-only";
    default:
      return "Unavailable";
  }
}

export function getTemplateAssetStatusClass(status: string | null | undefined): string {
  switch (status) {
    case "ready":
      return "border-positive-default/30 bg-positive-default/10 text-positive-stronger";
    case "read_only":
      return "border-accent-default/30 bg-accent-dimmer text-accent-stronger";
    case "needs_action":
      return "border-warning-default/30 bg-warning-dimmer text-warning-stronger";
    default:
      return "border-negative-default/30 bg-negative-dimmer text-negative-stronger";
  }
}

export function getTemplateRowStatusText(
  status: "matched" | "missing" | "invalid" | "orphaned"
): string {
  switch (status) {
    case "matched":
      return m.flow_template_fill_status_matched();
    case "invalid":
      return m.flow_template_fill_status_invalid();
    case "orphaned":
      return m.flow_template_fill_status_orphaned();
    case "missing":
    default:
      return m.flow_template_fill_status_missing();
  }
}

export function getTemplateRowStatusClass(
  status: "matched" | "missing" | "invalid" | "orphaned"
): string {
  switch (status) {
    case "matched":
      return "bg-positive-dimmer text-positive-stronger";
    case "invalid":
    case "orphaned":
      return "bg-negative-dimmer text-negative-stronger";
    case "missing":
    default:
      return "bg-warning-dimmer text-warning-stronger";
  }
}

export function getTemplateReadinessPillClass(readiness: {
  total: number;
  matched: number;
  incomplete: boolean;
}): string {
  if (!readiness.total) {
    return "bg-hover-dimmer text-secondary";
  }
  return readiness.incomplete
    ? "bg-warning-dimmer text-warning-stronger"
    : "bg-positive-dimmer text-positive-stronger";
}

// ---------------------------------------------------------------------------
// Summary display
// ---------------------------------------------------------------------------

export function getSummarySourceText(
  activeStep: FlowStep | null,
  summaryModel: { usesInputTemplate?: boolean } | null,
  previousStep: FlowStep | undefined | null
): string {
  if (!activeStep) return "";
  if (summaryModel?.usesInputTemplate) return m.flow_step_summary_source_input_template();
  switch (activeStep.input_source) {
    case "flow_input":
      return m.flow_step_summary_source_flow_input();
    case "previous_step":
      return previousStep
        ? m.flow_step_summary_source_previous_step({ order: String(previousStep.step_order) })
        : m.flow_step_summary_source_previous_step_unknown();
    case "all_previous_steps":
      return m.flow_step_summary_source_all_previous_steps();
    case "http_get":
      return m.flow_step_summary_source_http_get();
    case "http_post":
      return m.flow_step_summary_source_http_post();
    default:
      return activeStep.input_source;
  }
}

export function getSummaryNextChannelText(
  activeStep: FlowStep | null,
  summaryModel: { downstreamKind?: string } | null
): string {
  if (activeStep?.output_mode === "transcribe_only") {
    return m.flow_step_summary_next_channel_transcript();
  }
  return summaryModel?.downstreamKind === "text_and_structured"
    ? m.flow_step_summary_next_channel_text_and_structured()
    : m.flow_step_summary_next_channel_text();
}

// ---------------------------------------------------------------------------
// Validation issue message
// ---------------------------------------------------------------------------

export function getIssueMessage(
  issue: FlowStepValidationIssue | null,
  activeStep: FlowStep | null,
  previousStep: FlowStep | undefined | null
): string | null {
  if (!issue || !activeStep) return null;
  switch (issue.code) {
    case "typed_io_multiple_flow_input_steps":
    case "typed_io_flow_input_position_invalid":
      return m.flow_step_issue_flow_input_position();
    case "typed_io_invalid_input_source_position":
      return m.flow_step_issue_first_step_input_source();
    case "typed_io_missing_previous_step":
      return m.flow_step_issue_missing_previous_step();
    case "typed_io_document_source_unsupported":
    case "typed_io_audio_source_unsupported":
    case "typed_io_file_source_unsupported":
      return m.flow_step_issue_flow_input_only({
        inputType: getInputTypeLabel(activeStep.input_type)
      });
    case "typed_io_invalid_input_source_combination":
      return m.flow_step_issue_all_previous_steps_json();
    case "typed_io_incompatible_type_chain":
      return previousStep
        ? m.flow_typed_io_chain_incompatible({
            outputType: previousStep.output_type,
            inputType: activeStep.input_type,
            prevStep: String(previousStep.step_order)
          })
        : m.flow_step_issue_missing_previous_step();
    case "typed_io_unsupported_type":
      return activeStep.input_type === "image" ? m.flow_typed_io_image_not_supported() : null;
    default:
      return null;
  }
}
