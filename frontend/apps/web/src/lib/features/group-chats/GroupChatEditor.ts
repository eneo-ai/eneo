/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { createContext } from "$lib/core/context";
import { createResourceEditor } from "$lib/core/editing/ResourceEditor";
import type { Eneo, GroupChat } from "@eneo/eneo-js";

const [getGroupChatEditor, setGroupChatEditor] =
  createContext<ReturnType<typeof initGroupChatEditor>>("Edit a group chat");

/**
 * Initialize the ResourceEditor for GroupChat editing.
 * This editor supports tracking changes to:
 * - Basic properties (name, allow_mentions, show_response_label)
 * - Nested tool configurations including arrays of assistants and integrations
 *
 * For nested arrays like tools.assistants, only the ID field is tracked for changes,
 * which allows efficient diff generation when the list of assistants changes.
 *
 * @param data Configuration including the GroupChat to edit and callbacks
 * @returns A ResourceEditor instance for the GroupChat
 */
function initGroupChatEditor(data: {
  groupChat: GroupChat;
  eneo: Eneo;
  onUpdateDone?: (groupChat: GroupChat) => void;
}) {
  const editor = createResourceEditor({
    eneo: data.eneo,
    resource: data.groupChat,
    defaults: {
      insight_enabled: false
    },
    updateResource: async (resource, changes) => {
      const updated = await data.eneo.groupChats.update({ groupChat: resource, update: changes });
      data.onUpdateDone?.(updated);
      return updated;
    },
    editableFields: {
      name: true,
      allow_mentions: true,
      show_response_label: true,
      tools: {
        assistants: ["id", "user_description"]
      },
      insight_enabled: true
    },
    manageAttachements: false
  });

  setGroupChatEditor(editor);
  return editor;
}

export { initGroupChatEditor, getGroupChatEditor };
