import type { Assistant } from "@eneo/eneo-js";

export function isAssistant(item: unknown & { type: string }): item is Assistant {
  return item.type === "assistant";
}
