/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { GroupChat, GroupChatSparse } from "@eneo/eneo-js";

export function isGroupChat(item: unknown & { type: string }): item is GroupChat {
  return item.type === "assistant";
}

export function isGroupChatSparse(item: unknown & { type: string }): item is GroupChatSparse {
  return item.type === "assistant";
}
