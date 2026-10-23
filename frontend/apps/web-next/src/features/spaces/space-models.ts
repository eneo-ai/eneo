import type { ChatAppItem } from "@/features/assistants/assistants";
import type { Space } from "./space";

/** Display name of a space model: its nickname, else the model name. */
export function modelDisplayName(model: { name: string; nickname?: string | null }): string {
  return model.nickname?.trim() || model.name;
}

/** The chat model an assistant uses, when the space still offers it. */
export function assistantModelName(space: Space, item: ChatAppItem): string | null {
  if (item.type === "group-chat" || !item.completion_model_id) return null;
  const model = space.completion_models.find(
    (candidate) => candidate.id === item.completion_model_id
  );
  return model ? modelDisplayName(model) : null;
}
