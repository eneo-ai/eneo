import { page } from "$app/state";

export function getChatQueryParams({
  chatPartner,
  conversation,
  tab
}: {
  chatPartner?: { type: string; id?: string };
  conversation?: { id: string };
  tab?: "chat" | "history" | "insights";
}) {
  const currentParams = page.url.searchParams;
  const params = new URLSearchParams();

  // Build a map of parameters with fallbacks
  const paramMap: Record<string, string | undefined> = {
    session_id: conversation?.id ?? currentParams.get("session_id") ?? undefined,
    tab: tab ?? currentParams.get("tab") ?? undefined
  };

  // Only add partner info if not a default assistant
  if (chatPartner?.type !== "default-assistant") {
    paramMap["type"] = chatPartner?.type ?? currentParams.get("type") ?? undefined;
    paramMap["id"] = chatPartner?.id ?? currentParams.get("id") ?? undefined;
  }

  for (const [param, value] of Object.entries(paramMap)) {
    if (value) params.set(param, value);
  }

  return params.toString();
}
