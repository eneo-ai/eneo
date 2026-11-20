/** @typedef {import('../types/resources').ConversationSettings} Settings */

/**
 * Apply only the choices a user changed to the latest conversation revision.
 * Each tool has its own choice, including tools no longer shown in the picker.
 * @param {Settings} settings
 * @param {Partial<Settings>} patch
 * @returns {Settings}
 */
export function applyConversationSettingsPatch(settings, patch) {
  const next = { ...settings, ...patch };
  if (patch.mcp_server_states)
    next.mcp_server_states = { ...settings.mcp_server_states, ...patch.mcp_server_states };
  if (patch.capability_states)
    next.capability_states = { ...settings.capability_states, ...patch.capability_states };
  return next;
}
