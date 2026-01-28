/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See LICENSE file in the repository root for full license text.
*/

import { createContext } from "$lib/core/context";
import { createResourceEditor } from "$lib/core/editing/ResourceEditor";
import type { Intric, Space } from "@intric/intric-js";

const [getSpaceSettingsEditor, setSpaceSettingsEditor] = createContext<
  ReturnType<typeof createSpaceSettingsEditor>
>("Space Settings Editor");

type SpaceSettingsEditorParams = {
  space: Space;
  intric: Intric;
  onUpdateDone?: (space: Space) => void;
};

function createSpaceSettingsEditor(data: SpaceSettingsEditorParams) {
  const editor = createResourceEditor({
    resource: data.space,
    defaults: {
      description: "",
      data_retention_days: null
    },
    updateResource: async (resource, changes) => {
      const updated = await data.intric.spaces.update({
        space: { id: resource.id },
        update: changes
      });
      data.onUpdateDone?.(updated);
      return updated;
    },
    editableFields: {
      name: true,
      description: true,
      data_retention_days: true,
      icon_id: true
    },
    // Space doesn't have attachments like assistants
    manageAttachements: false,
    intric: data.intric
  });

  return editor;
}

function initSpaceSettingsEditor(data: SpaceSettingsEditorParams) {
  const editor = createSpaceSettingsEditor(data);
  setSpaceSettingsEditor(editor);
  return editor;
}

export { initSpaceSettingsEditor, getSpaceSettingsEditor };
