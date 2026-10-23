import type { ChatPartnerType } from "./types";

type Translate = (key: string, values?: Record<string, string>) => string;

/**
 * The name the backend seeds every space's default assistant with
 * (backend/src/eneo/spaces/space_init_service.py). A default assistant still
 * carrying it has not been named by anyone, so the UI names it after its
 * space instead; a renamed one keeps its owner's name.
 */
const SEEDED_DEFAULT_NAME = "Default";

/**
 * The name a chat partner is shown under. The default assistant of the user's
 * personal space is the personal assistant, which the dashboard and the ⌘K
 * palette already call "Personlig assistent". A shared space's default
 * assistant that nobody renamed is "Assistent för <ytan>" (or a generic
 * "Ytans assistent" when the space is unknown). Decided by type, space and
 * whether the seeded name was ever changed, never by matching a user's name.
 */
export function displayPartnerName(
  partner: {
    type: ChatPartnerType;
    name: string;
    personalSpace?: boolean;
    spaceName?: string | null;
  },
  t: Translate
): string {
  if (partner.type !== "default-assistant") return partner.name;
  if (partner.personalSpace) return t("personal_assistant");
  if (partner.name !== SEEDED_DEFAULT_NAME) return partner.name;
  return partner.spaceName
    ? t("space_default_assistant_named", { space: partner.spaceName })
    : t("space_default_assistant");
}
