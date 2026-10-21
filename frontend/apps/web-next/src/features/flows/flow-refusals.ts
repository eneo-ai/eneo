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
    return t("flows_refusal_read_lost_producer", {
      reader: labelAt(steps, context.step_order, t, context.step_id),
      producer: labelAt(steps, context.reads_step, t),
      site: siteLabel(context.site, t)
    });
  }
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
