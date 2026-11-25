import type { Assistant } from "@eneo/eneo-js";

const validTypes: Assistant["type"][] = ["assistant", "default-assistant"] as const;
export type ValidChatPartnerType = (typeof validTypes)[number];

export function isValidChatPartnerType(type: string): type is ValidChatPartnerType {
  // We cast, otherwise TS will complain about type not being compatible
  return (validTypes as string[]).includes(type);
}
