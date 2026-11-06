/**
 * Browser start choices for new conversations, shared by both clients.
 * Saved conversation state and revisions remain server-owned.
 *
 * @typedef {import('../types/resources').ConversationSettings} Settings
 * @typedef {import('../types/resources').ConversationSettingsResolution} Resolution
 * @typedef {{tenantId: string, userId: string, partnerId: string, partnerType: string}} Scope
 */

/** @param {Scope} scope */
function storageKey(scope) {
  return `eneo:conversation-draft:${JSON.stringify([
    scope.tenantId,
    scope.userId,
    scope.partnerType,
    scope.partnerId
  ])}`;
}

/** @param {unknown} value @returns {value is Record<string, unknown>} */
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** @param {unknown} value @returns {value is Record<string, boolean>} */
function isSelectionMap(value) {
  return (
    isRecord(value) &&
    Object.keys(value).length <= 512 &&
    Object.values(value).every((selected) => typeof selected === "boolean")
  );
}

/** Storage is optional: blocked access, corrupt data and unknown formats use defaults.
 * @param {Scope} scope
 * @returns {Settings | undefined}
 */
export function readConversationDraft(scope) {
  try {
    const raw = globalThis.localStorage.getItem(storageKey(scope));
    if (!raw || raw.length > 100_000) return;
    /** @type {unknown} */
    const value = JSON.parse(raw);
    if (!isRecord(value) || value.version !== 1 || !isRecord(value.settings)) return;
    const s = value.settings;
    if (
      Object.keys(s).some(
        (key) =>
          ![
            "completion_model_id",
            "reasoning_effort",
            "require_tool_approval",
            "mcp_server_states",
            "capability_states"
          ].includes(key)
      )
    )
      return;
    if (s.completion_model_id != null && typeof s.completion_model_id !== "string") return;
    if (
      s.reasoning_effort != null &&
      (typeof s.reasoning_effort !== "string" || s.reasoning_effort.length > 32)
    )
      return;
    if (
      typeof s.require_tool_approval !== "boolean" ||
      !isSelectionMap(s.mcp_server_states) ||
      !isSelectionMap(s.capability_states)
    )
      return;
    return {
      completion_model_id: s.completion_model_id ?? null,
      reasoning_effort: s.reasoning_effort ?? null,
      require_tool_approval: s.require_tool_approval,
      mcp_server_states: s.mcp_server_states,
      capability_states: s.capability_states
    };
  } catch {
    return;
  }
}

/** Best effort only; failure to remember a preference must never fail a chat.
 * @param {Scope} scope
 * @param {Settings} settings
 */
export function rememberConversationDraft(scope, settings) {
  try {
    globalThis.localStorage.setItem(
      storageKey(scope),
      JSON.stringify({
        version: 1,
        settings: {
          ...settings,
          require_tool_approval: settings.require_tool_approval ?? false,
          mcp_server_states: settings.mcp_server_states ?? {},
          capability_states: settings.capability_states ?? {}
        }
      })
    );
  } catch {
    // Storage may be unavailable or full. The current conversation still works.
  }
}

/** Only NEW drafts may fall back when remembered choices are no longer usable.
 * Saved conversations must keep their explicit unavailable-model recovery flow.
 * @param {(settings?: Settings) => Promise<Resolution>} resolve
 * @param {Settings | undefined} remembered
 * @returns {Promise<Resolution>}
 */
export async function resolveConversationDraft(resolve, remembered) {
  let resolved;
  try {
    resolved = await resolve(remembered);
  } catch (error) {
    // A browser value from a retired API format is disposable. Server/network
    // failures still surface; they must not silently replace user choices.
    if (!remembered || !isRecord(error) || error.status !== 422) throw error;
    return resolve();
  }
  if (remembered && resolved.model_unavailable) {
    const defaults = await resolve();
    resolved = await resolve({
      ...remembered,
      completion_model_id: defaults.settings.completion_model_id,
      reasoning_effort: null
    });
  }
  const effort = resolved.settings.reasoning_effort;
  if (effort && !resolved.reasoning_effort_options?.includes(effort)) {
    resolved = await resolve({ ...resolved.settings, reasoning_effort: null });
  }
  return resolved;
}
