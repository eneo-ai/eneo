import { EneoError } from "@eneo/eneo-js";

const QUERY_ERROR_CODE = 9003;

type ContextErrorInfo = {
  used?: number;
  limit?: number;
};

export function isConversationSubmitDisabled(state: {
  isLoading: boolean;
  isUploading: boolean;
  hasContent: boolean;
  hasCompletionModel: boolean;
  estimatedExceedsContext: boolean;
}): boolean {
  // The estimate is advisory. Only the provider can authoritatively reject
  // the final payload after all model-specific tokenization has been applied.
  return state.isLoading || state.isUploading || !state.hasContent || !state.hasCompletionModel;
}

export function getContextErrorInfo(error: unknown): ContextErrorInfo | null {
  if (error instanceof EneoError) {
    const details = error.response?.details;
    const used = details?.tokens_used;
    const limit = details?.token_limit;
    if (error.code === QUERY_ERROR_CODE) {
      return {
        used: typeof used === "number" ? used : undefined,
        limit: typeof limit === "number" ? limit : undefined
      };
    }
  }

  const message = error instanceof Error ? error.message : String(error);
  const lower = message.toLowerCase();
  const isContextError =
    lower.includes("context window") ||
    lower.includes("context length") ||
    lower.includes("maximum context") ||
    lower.includes("too many tokens") ||
    lower.includes("tokens used") ||
    lower.includes("too long");
  if (!isContextError) return null;

  const match = message.match(/(\d[\d,]*)\s*tokens?\s*used.*?limit\s*(?:is\s*)?(\d[\d,]*)/i);
  if (!match) return {};

  return {
    used: parseInt(match[1].replace(/,/g, "")),
    limit: parseInt(match[2].replace(/,/g, ""))
  };
}
