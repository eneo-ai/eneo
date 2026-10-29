export function readChatTab(search: Pick<URLSearchParams, "get">): "chat" | "insights" {
  return search.get("tab") === "insights" ? "insights" : "chat";
}
