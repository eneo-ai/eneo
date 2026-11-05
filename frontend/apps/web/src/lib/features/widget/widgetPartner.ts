import type { Assistant, WidgetPublicConfig } from "@eneo/eneo-js";

/**
 * The chat partner the ChatService drives inside the embed page.
 *
 * Visitors never see the assistant's real configuration (model, tools,
 * knowledge), so this is a display-only stand-in: enough for the service to
 * consider the partner askable, with every capability switched off.
 */
export function widgetChatPartner(config: WidgetPublicConfig): Assistant {
  const partner = {
    id: config.public_id,
    type: "assistant",
    name: config.texts.title || config.name,
    description: config.texts.welcome || null,
    published: true,
    // A placeholder model so `hasCompletionModel` is true; the backend picks
    // the real one and never reveals it here.
    completion_model: {
      id: "widget",
      name: "",
      nickname: "",
      token_limit: null,
      vision: false,
      reasoning: false,
      is_locked: true,
      can_access: true
    },
    completion_model_kwargs: {},
    attachments: [],
    tools: { assistants: [] },
    enabled_capabilities: [],
    mcp_servers: [],
    effective_config: null,
    permissions: []
  };
  return partner as unknown as Assistant;
}
