import {
  EneoApiError,
  getErrorMessage,
  getErrorMessageForCode,
  getErrorMessageForReason
} from "@/lib/api/errors";
import { refusalAnchor, refusalMessage, type FieldAnchor } from "./editor/field-problems";
import { readTemplateFill } from "./editor/step-configs";
import type { FlowStep } from "./flows-api";
import { stepLabel } from "./flow-labels";
import { speakerStepLacksTranscript } from "./flow-transcription";

/** next-intl's translator, as far as the refusals use it. */
type Translator = {
  (key: string, values?: Record<string, string | number>): string;
  has: (key: string) => boolean;
};

/** The draft moved on since it was read: the caller reloads it and says so. */
export const STALE_REVISION = "stale_revision";
/** A step would lose (or change) a step it reads. */
export const READ_LOST_PRODUCER = "flow_step_read_lost_producer";
/** The change removes a run form field a step still reads. */
export const FORM_FIELD_STILL_READ = "flow_form_field_still_read";
/** The flow is not published (an unpublish of a flow someone else unpublished). */
export const NOT_PUBLISHED = "flow_not_published";

/** What happened to the read, as the core names it in `context.reason`. */
const READ_REASONS = new Set([
  "producer_removed",
  "producer_moved_after_reader",
  "reader_moved_before_producer",
  "producer_renamed",
  "would_read_another_step"
]);

/**
 * The sentence for a read the core names, by why it reads nothing: a name the
 * flow does not have, a step with no result yet, a step order the flow does
 * not have, or a part its value does not have.
 */
const REFERENCE_SENTENCES: Record<string, string> = {
  flow_input_binding_invalid_step_reference: "flows_refusal_reference_unknown",
  flow_input_binding_future_step_reference: "flows_refusal_reference_later",
  flow_input_binding_unknown_step_order: "flows_refusal_reference_no_step",
  flow_input_binding_unsupported_key: "flows_refusal_reference_path"
};

/** Where in a step a read sits, as the core names it (`prompt`, `input_bindings.question`). */
function siteLabel(site: unknown, t: Translator): string {
  if (typeof site !== "string") return t("flows_refusal_site_unknown");
  if (site === "prompt") return t("flows_refusal_site_prompt");
  if (site.startsWith("input_bindings")) return t("flows_refusal_site_bindings");
  if (site.startsWith("input_config")) return t("flows_refusal_site_input_config");
  if (site.startsWith("output_config")) return t("flows_refusal_site_output_config");
  return t("flows_refusal_site_unknown");
}

function stepAt(steps: readonly FlowStep[], order: unknown, id?: unknown): FlowStep | null {
  return (
    steps.find((step) => typeof id === "string" && step.id === id) ??
    steps.find((step) => step.step_order === order) ??
    null
  );
}

/**
 * The draft check's sentence for a step refusal the core words only in
 * general (`flow_step_invalid`), when the check already knows the cause.
 */
function draftCheckSentence(
  code: string | null | undefined,
  step: FlowStep | null,
  steps: readonly FlowStep[],
  t: Translator
): string | null {
  if (code !== "flow_step_invalid" || !step) return null;
  if (speakerStepLacksTranscript(step, steps)) {
    return t("flow_editor_tools_check_speaker_transcript_missing");
  }
  if (step.output_mode !== "template_fill") return null;
  return readTemplateFill(step.output_config).templateAssetId
    ? null
    : t("flow_editor_tools_check_template_missing");
}

/**
 * What a refusal names, for its sentence: the read (`reference`; a path's
 * `key`, except a key of the underlag itself or a step it lists in
 * `source_refs`), as written in braces, the Word field (`placeholder`) and
 * where in the step (`site`). Empty when not named.
 */
const KEY_IS_NO_READ = new Set(["input_bindings", "input_bindings.source_refs"]);

function namedValues(context: Record<string, unknown>, t: Translator) {
  const text = (value: unknown) => (typeof value === "string" ? value : "");
  const read =
    text(context.reference) || (KEY_IS_NO_READ.has(text(context.field)) ? "" : text(context.key));
  return {
    reference: read ? `{{${read}}}` : "",
    placeholder: text(context.placeholder),
    site: siteLabel(context.field, t)
  };
}

function labelAt(steps: readonly FlowStep[], order: unknown, t: Translator, id?: unknown) {
  const step = stepAt(steps, order, id);
  if (step) return stepLabel(step, t);
  return typeof order === "number"
    ? t("flows_step_label_unnamed", { order })
    : t("flows_refusal_some_step");
}

/**
 * A refusal from the flow core as a sentence a person can act on: what was
 * refused and how to fix it, with the steps it names by their names.
 * `steps` is the draft the refused change was made against (the step orders
 * in a refusal are that draft's). Codes the app has no sentence for fall
 * back to the reader's sentence for the issue or the code (the step editor's
 * catalog), then to a general Swedish line: the core's own message is
 * English and meant for developers, so it is never shown.
 */
export function flowRefusalMessage(
  error: unknown,
  steps: readonly FlowStep[],
  t: Translator
): string {
  if (!(error instanceof EneoApiError)) return getErrorMessage(error, t);
  const code = error.reason;
  const context = error.context ?? {};

  if (code === STALE_REVISION) return t("flows_refusal_stale_revision");
  if (code === READ_LOST_PRODUCER) {
    const values = {
      reader: labelAt(steps, context.step_order, t, context.step_id),
      producer: labelAt(steps, context.reads_step, t),
      site: siteLabel(context.site, t),
      name: typeof context.reads_name === "string" ? context.reads_name : ""
    };
    const reason = typeof context.reason === "string" ? context.reason : null;
    if (reason && READ_REASONS.has(reason) && (reason !== "producer_renamed" || values.name)) {
      return t(`flows_refusal_read_${reason}`, values);
    }
    return t("flows_refusal_read_lost_producer", values);
  }
  if (code === FORM_FIELD_STILL_READ) {
    const fields = Array.isArray(context.fields)
      ? context.fields.filter((field): field is string => typeof field === "string")
      : [];
    const readers = Array.isArray(context.readers) ? context.readers : [];
    const readerLabels = [
      ...new Set(
        readers.map((reader) => {
          const item = (reader ?? {}) as Record<string, unknown>;
          return labelAt(steps, item.step_order, t, item.step_id);
        })
      )
    ];
    return t("flows_refusal_form_field_still_read", {
      count: Math.max(fields.length, 1),
      fields: fields.join(", "),
      readers: readerLabels.length > 0 ? readerLabels.join(", ") : t("flows_refusal_some_step")
    });
  }
  if (code === NOT_PUBLISHED) return t("flows_refusal_not_published");
  if (code === "insufficient_space_permission") return t("flows_refusal_no_permission");

  const issue = typeof context.issue_code === "string" ? context.issue_code : null;
  const values = namedValues(context, t);
  const named = values.reference
    ? (REFERENCE_SENTENCES[issue ?? ""] ?? REFERENCE_SENTENCES[code ?? ""])
    : undefined;
  const message =
    (named ? t(named, values) : null) ??
    refusalMessage(issue, t, values) ??
    draftCheckSentence(code, stepAt(steps, context.step_order, context.step_id), steps, t) ??
    refusalMessage(code, t, values) ??
    getErrorMessageForReason(code, t) ??
    getErrorMessageForCode(error.code, t);
  // Publication refusals name the step they are about; the page offers to open it.
  if (typeof context.step_order === "number") {
    const step = labelAt(steps, context.step_order, t, context.step_id);
    return message
      ? t("flows_refusal_in_step", { step, message })
      : t("flows_refusal_step_generic", { step });
  }
  return message ?? t("request_failed");
}

/**
 * The step of the draft a refusal is about and the field in it, for a way to
 * open it there; null when it names no step of the draft.
 */
export function refusalStep(
  error: unknown,
  steps: readonly FlowStep[]
): { step: FlowStep; anchor: FieldAnchor | null } | null {
  if (!(error instanceof EneoApiError)) return null;
  const context = error.context ?? {};
  if (context.step_order === undefined && context.step_id === undefined) return null;
  const step = stepAt(steps, context.step_order, context.step_id);
  if (!step) return null;
  // A lost read names its place as `site`, a publication refusal as `field`.
  const field =
    [context.field, context.site].find((value): value is string => typeof value === "string") ??
    null;
  return { step, anchor: refusalAnchor(context, error.reason, step, field) };
}
