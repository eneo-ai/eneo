import { m } from "$lib/paraglide/messages";
import { countMessage } from "$lib/features/flows/flowCount";

export type FlowRunDialogLabels = ReturnType<typeof getFlowRunDialogLabels>;

/**
 * The run dialog's words, gathered once so the dialog and its parts are handed
 * the same set. Every sentence lives in Paraglide; a count picks its singular
 * form here so no part of the dialog can show "1 filer".
 */
export function getFlowRunDialogLabels() {
  return {
    progress: (current: number, total: number) =>
      m.flow_run_dialog_progress({ current: String(current), total: String(total) }),
    previous: m.back(),
    next: m.next(),
    audio: m.flow_run_dialog_format_audio(),
    file: m.flow_run_dialog_format_file(),
    document: m.flow_run_dialog_format_document(),
    unnamedStep: (stepOrder: number) => m.flow_step_fallback_label({ order: String(stepOrder) }),
    templateReady: m.flow_run_dialog_template_ready(),
    templateNeedsAction: m.flow_run_dialog_template_needs_action(),
    templateReadOnly: m.flow_run_dialog_template_read_only(),
    templateUnavailable: m.flow_run_dialog_template_unavailable(),
    templateReadOnlyMessage: m.flow_run_dialog_template_read_only_message(),
    templateNeedsActionMessage: m.flow_run_dialog_template_needs_action_message(),
    templateStatusTitle: m.flow_run_dialog_template_status_title(),
    templateStatusDescription: m.flow_run_dialog_template_status_description(),
    templateUnnamed: m.flow_run_dialog_template_unnamed(),
    retryUpload: m.flow_retry(),
    runtimeUploadHint: m.flow_run_dialog_upload_hint(),
    runtimeUploadingHint: m.flow_run_dialog_uploading_hint(),
    discardRecordingBusy: m.flow_run_dialog_discard_recording_busy(),
    saveForLaterBusy: m.flow_run_dialog_save_for_later_busy(),
    saveForLaterOnlyInTab: m.flow_run_dialog_save_for_later_only_in_tab(),
    allowedTypesToggle: m.flow_run_dialog_allowed_types_toggle(),
    maxFiles: (count: number) =>
      countMessage(count, m.flow_run_dialog_max_files_one, m.flow_run_dialog_max_files),
    maxFileSize: (size: string) => m.flow_run_dialog_max_file_size({ size }),
    maxFilesReached: m.flow_run_dialog_max_files_reached(),
    requiredBadge: m.flow_run_dialog_required_badge(),
    selectedFiles: (count: number) =>
      countMessage(count, m.flow_run_dialog_selected_files_one, m.flow_run_dialog_selected_files),
    runBlockersTitle: m.flow_run_dialog_blockers_title(),
    reviewReady: m.flow_run_dialog_review_ready(),
    reviewSummaryTitle: m.flow_run_dialog_review_summary_title(),
    reviewFieldsTitle: m.flow_run_dialog_review_fields_title(),
    reviewTextTitle: m.flow_run_dialog_review_text_title(),
    reviewFilesTitle: m.flow_run_dialog_review_files_title(),
    runtimeReviewStep: (stepOrder: number, stepLabel: string) =>
      m.flow_run_dialog_step_with_label({ order: String(stepOrder), label: stepLabel }),
    closeConfirmTitle: m.flow_run_dialog_close_confirm_title(),
    closeConfirmMessage: m.flow_run_dialog_close_confirm_message(),
    closeConfirmDiscard: m.flow_run_dialog_close_confirm_discard(),
    closeConfirmKeep: m.flow_run_dialog_close_confirm_keep(),
    technicalMimeToggle: m.flow_run_dialog_technical_types_toggle()
  };
}
