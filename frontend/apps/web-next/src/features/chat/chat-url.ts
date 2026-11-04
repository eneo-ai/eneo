/** A chat page view, as Svelte's chat page names them in `?tab=`. */
export type ChatTab = "chat" | "history" | "insights";

export function readChatTab(search: Pick<URLSearchParams, "get">): ChatTab {
  const tab = search.get("tab");
  return tab === "history" || tab === "insights" ? tab : "chat";
}

/** The panels the header's tabs control (aria-controls). */
export const CHAT_PANEL_IDS: Record<ChatTab, string> = {
  chat: "chat-panel-chat",
  history: "chat-panel-history",
  insights: "chat-panel-insights"
};
