import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

/*
 * The organisation's settings for the helper chat on assistants: on or off,
 * the default model (the one value the flow chat's default is too) and the
 * organisation's guidance added to the helper's built-in instructions. One
 * endpoint; a PATCH changes the fields it sends and answers with all three.
 */

export type HelperChatPolicy = Schema<"HelperChatPolicyPublic">;
export type HelperChatPolicyUpdate = Schema<"HelperChatPolicyUpdate">;

export const HELPER_CHAT_POLICY_KEY = ["admin-helper-chat-policy"] as const;

/** Every save on the page goes through one queue, so the last answer is the latest policy. */
export const HELPER_CHAT_POLICY_QUEUE = "helper-chat-policy";

export function helperChatPolicyQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: HELPER_CHAT_POLICY_KEY,
    queryFn: (): Promise<HelperChatPolicy> => unwrap(api.GET("/api/v1/settings/helper-chat-policy"))
  });
}

export function updateHelperChatPolicy(
  api: EneoClient,
  body: HelperChatPolicyUpdate
): Promise<HelperChatPolicy> {
  return unwrap(api.PATCH("/api/v1/settings/helper-chat-policy", { body }));
}

/** next-intl's translator, as far as these helpers use it. */
type Translate = (key: string, values?: Record<string, string | number>) => string;

const MODEL_REFUSALS: Record<string, string> = {
  helper_chat_policy_model_unavailable: "admin_helper_error_model_unavailable",
  helper_chat_policy_model_without_tools: "admin_helper_error_model_without_tools"
};

/** A refused default model in words: what was wrong and what to do. */
export function modelRefusalMessage(error: unknown, t: Translate): string {
  const key = error instanceof EneoApiError && error.reason ? MODEL_REFUSALS[error.reason] : null;
  return key ? t(key) : `${getErrorMessage(error, t)} ${t("admin_helper_model_try_again")}`;
}

/**
 * The guidance's length as the server counts it (Unicode code points), which
 * is what the maximum the API reports is measured in.
 */
export function guidanceLength(text: string): number {
  return Array.from(text).length;
}

/** The guidance is over the maximum: the problem shown at the field, in words. */
export function guidanceTooLongMessage(max: number, t: Translate): string {
  return t("admin_helper_guidance_too_long", { max });
}

/**
 * A validation refusal (422) that names the guidance as too long: its errors
 * as `details.errors` with a `location`, or as FastAPI's list with a `loc`.
 */
function isGuidanceTooLong(error: unknown): boolean {
  if (!(error instanceof EneoApiError) || error.status !== 422) return false;
  const details: unknown = error.details;
  const errors: unknown = Array.isArray(details)
    ? details
    : (details as { errors?: unknown } | null | undefined)?.errors;
  if (!Array.isArray(errors)) return false;
  return errors.some((entry: unknown) => {
    if (typeof entry !== "object" || entry === null) return false;
    const { location, loc, type } = entry as { location?: unknown; loc?: unknown; type?: unknown };
    const path = location ?? loc;
    return (
      Array.isArray(path) && path[path.length - 1] === "guidance" && type === "string_too_long"
    );
  });
}

/**
 * A refused guidance save, shown at the field: too long in the page's own
 * words, anything else in the shared catalog's, each with what to do.
 */
export function guidanceRefusalMessage(error: unknown, max: number, t: Translate): string {
  if (isGuidanceTooLong(error)) return guidanceTooLongMessage(max, t);
  return `${getErrorMessage(error, t)} ${t("admin_helper_guidance_try_again")}`;
}
