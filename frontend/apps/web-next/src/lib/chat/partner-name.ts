import type { ChatPartnerType } from "./types";

type Translate = (key: string) => string;

/**
 * The name a chat partner is shown under. Every space gets a default
 * assistant the backend calls "Default"; the one in the user's personal space
 * is the personal assistant, which the dashboard and the ⌘K palette already
 * call "Personlig assistent". Decided by the partner's type and space, never
 * by its name. Every other partner (including another space's default
 * assistant) keeps the name its owner gave it.
 */
export function displayPartnerName(
  partner: { type: ChatPartnerType; name: string; personalSpace?: boolean },
  t: Translate
): string {
  return partner.type === "default-assistant" && partner.personalSpace
    ? t("personal_assistant")
    : partner.name;
}
