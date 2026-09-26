import type { RecentConversation } from "@/lib/api/conversations";

type Translate = (key: string, values?: Record<string, string>) => string;

/**
 * Who a conversation is with, where its title alone doesn't say:
 * "Avtalsgranskaren i Upphandling". Null for the personal chat, which needs
 * no introduction in the user's own navigation.
 */
export function conversationContext(
  { partner, space }: Pick<RecentConversation, "partner" | "space">,
  t: Translate
): string | null {
  if (space.personal && partner.type === "default-assistant") return null;
  const spaceName = space.personal
    ? t("personal")
    : space.organization
      ? t("organization")
      : space.name;
  return t("recent_partner_in_space", { partner: partner.name, space: spaceName });
}
