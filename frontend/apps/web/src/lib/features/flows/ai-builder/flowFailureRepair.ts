import { m } from "$lib/paraglide/messages";
import type { AIBuilderError } from "./protocol";

/** Why a failed step cannot be handed to the Builder, in the user's words.
 *  The server decides; the reason travels in the error's details. A refusal
 *  that names its cause is final for this run; only an unexplained failure
 *  is worth retrying. */
export function repairFailureCopy(error: AIBuilderError): {
  title: string;
  body: string;
  retry: boolean;
} {
  if (error.code === "flow_not_published") {
    return {
      title: m.ai_builder_review_unpublished_title(),
      body: m.ai_builder_review_unpublished_body(),
      retry: false
    };
  }
  if (error.code === "review_stale") {
    return {
      title: m.ai_builder_repair_stale_title(),
      body: m.ai_builder_repair_stale_body(),
      retry: false
    };
  }
  if (error.code === "review_finding_unknown") {
    const reason = error.details?.reason;
    if (reason === "no_failed_attempt") {
      return {
        title: m.ai_builder_repair_succeeded_later_title(),
        body: m.ai_builder_repair_succeeded_later_body(),
        retry: false
      };
    }
    if (reason === "step_unknown") {
      return {
        title: m.ai_builder_repair_step_unknown_title(),
        body: m.ai_builder_repair_step_unknown_body(),
        retry: false
      };
    }
    return {
      title: m.ai_builder_repair_output_not_retained_title(),
      body: m.ai_builder_repair_output_not_retained_body(),
      retry: false
    };
  }
  return { title: m.ai_builder_repair_load_failed(), body: error.message, retry: true };
}
