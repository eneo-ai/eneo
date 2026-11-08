import { EneoError, type ConversationSettings } from "@eneo/eneo-js";

const QUERY_ERROR_CODE = 9003;
const CAPABILITY_ID_PREFIX = "capability:";

type ToolSelectionUpdate = Required<
  Pick<ConversationSettings, "mcp_server_states" | "capability_states">
>;

/**
 * Which settings controls are disabled. A save in flight disables nothing:
 * the control the user just operated keeps focus (WCAG 2.4.3) and a change
 * made meanwhile waits for its turn in ChatService.
 */
export function settingsControlsDisabled(state: {
  hasSettings: boolean;
  /** A turn is streaming. */
  isLoading: boolean;
  settingsCompatible: boolean;
  modelUnavailable: boolean;
}): { model: boolean; modelDependent: boolean } {
  const model = !state.hasSettings || state.isLoading || !state.settingsCompatible;
  // Every save but the pick of a replacement model is rejected while the
  // saved model is unavailable.
  return { model, modelDependent: model || state.modelUnavailable };
}

/**
 * The settings update for a tool selection. Only tools whose state differs
 * from what is selected now are written: a tool the user never touched
 * stays absent and keeps following the admin default, and explicit choices
 * already saved are kept. Null when nothing changed.
 */
export function toolSelectionUpdate(
  settings:
    Pick<ConversationSettings, "mcp_server_states" | "capability_states"> | null | undefined,
  tools: ReadonlyArray<{ id: string; selected: boolean }>,
  disabledIds: ReadonlySet<string>
): ToolSelectionUpdate | null {
  const mcp_server_states = { ...settings?.mcp_server_states };
  const capability_states = { ...settings?.capability_states };
  let changed = false;
  for (const tool of tools) {
    const on = !disabledIds.has(tool.id);
    if (on === tool.selected) continue;
    changed = true;
    if (tool.id.startsWith(CAPABILITY_ID_PREFIX)) {
      capability_states[tool.id.slice(CAPABILITY_ID_PREFIX.length)] = on;
    } else {
      mcp_server_states[tool.id] = on;
    }
  }
  return changed ? { mcp_server_states, capability_states } : null;
}

type ContextErrorInfo = {
  used?: number;
  limit?: number;
};

export function isConversationSubmitDisabled(state: {
  /** A conversation request is streaming. */
  isLoading: boolean;
  /**
   * A send has started but the conversation request has not been issued yet
   * (for example while a queued model switch settles). Without this, a second
   * Enter in that window would start an overlapping request that hides the
   * first one's message.
   */
  sendPending: boolean;
  hasContent: boolean;
  hasCompletionModel: boolean;
  estimatedExceedsContext: boolean;
}): boolean {
  // The estimate is advisory. Only the provider can authoritatively reject
  // the final payload after all model-specific tokenization has been applied.
  // Attachments still uploading do not block either: the message is sent as
  // soon as they finish, and it waits as a pending message meanwhile.
  return state.isLoading || state.sendPending || !state.hasContent || !state.hasCompletionModel;
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
