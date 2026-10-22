import { EneoApiError, getErrorMessage } from "@/lib/api/errors";
import type { FlowStep } from "./flows-api";
import { stepLabel } from "./flow-labels";

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
 * back to the reference catalog's `flow_error_<code>`, then to the core's
 * own message.
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

  const catalogKey = code ? `flow_error_${code}` : null;
  const message = catalogKey && t.has(catalogKey) ? t(catalogKey) : getErrorMessage(error, t);
  // Publication refusals name the step they are about.
  if (typeof context.step_order === "number") {
    return t("flows_refusal_in_step", {
      step: labelAt(steps, context.step_order, t),
      message
    });
  }
  return message;
}
