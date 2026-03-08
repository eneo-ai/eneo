/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { createContext } from "$lib/core/context";
import { writable, get } from "svelte/store";
import type { Intric, Prompt, PromptSparse } from "@intric/intric-js";
import { browser } from "$app/environment";

const [getPromptManager, setPromptManager] =
  createContext<ReturnType<typeof createPromptManager>>("Prompt version history");

type PromptManagerParams = {
  intric: Intric;
  /**
   * Pass in
   * */
  loadPromptVersionHistory: () => Promise<PromptSparse[]>;
  /**
   * This function will be run when a user selects a prompt;
   * use it to update your resource (e.g. assistant)
   * */
  onPromptSelected: (prompt: Prompt) => void;
};

function initPromptManager(data: PromptManagerParams) {
  const context = createPromptManager(data);
  setPromptManager(context);
  return context;
}

function createPromptManager(params: PromptManagerParams) {
  const { intric, loadPromptVersionHistory, onPromptSelected } = params;
  const allPrompts = writable<PromptSparse[]>([]);
  const previewedPrompt = writable<Prompt | null>(null);
  const showPromptVersionDialog = writable(false);

  async function init() {
    if (browser) {
      const prompts = await loadPromptVersionHistory();
      allPrompts.set(prompts);
      const currentPrompt = prompts.find((prompt) => prompt.is_selected);
      if (currentPrompt) {
        loadPreview(currentPrompt);
      }
    }
  }

  init();

  // Refresh prompt history each time the dialog re-opens (not on initial mount)
  let dialogHasBeenClosed = false;
  showPromptVersionDialog.subscribe((isOpen) => {
    if (isOpen && browser && dialogHasBeenClosed) {
      void refreshPrompts();
    }
    if (!isOpen) dialogHasBeenClosed = true;
  });

  async function deletePrompt({ id }: { id: string }) {
    try {
      await intric.prompts.delete({ id });
      allPrompts.update(($allPrompts) => $allPrompts.filter((prompt) => prompt.id !== id));
      if (id === get(previewedPrompt)?.id) {
        previewedPrompt.set(null);
      }
    } catch (e) {
      alert(`Error deleting prompt with id: ${id}`);
    }
  }

  async function refreshPrompts() {
    try {
      const updated = await loadPromptVersionHistory();
      allPrompts.set(updated);
      return updated;
    } catch (e) {
      console.error("Error while loding prompt history", e);
    }
  }

  async function updatePromptDescription({
    id,
    description
  }: {
    id: string;
    description?: string;
  }) {
    try {
      const update = await intric.prompts.update({ prompt: { id }, update: { description } });
      // If we updated the prompt of the current preview, update the preview
      previewedPrompt.update(($previewedPrompt) => {
        return update.id === $previewedPrompt?.id ? update : $previewedPrompt;
      });
      allPrompts.update(($allPrompts) => {
        $allPrompts.forEach((prompt) => {
          if (prompt.id === update.id) {
            prompt.description = update.description;
          }
        });
        return $allPrompts;
      });
    } catch (e) {
      console.error("Error while updating prompt: ", e);
    }
  }

  async function loadPreview({ id }: { id: string }) {
    try {
      const preview = await intric.prompts.get({ id });
      previewedPrompt.set(preview);
      return previewedPrompt;
    } catch (e) {
      console.error("Error while loading prompt preview: ", e);
    }
  }

  return Object.freeze({
    state: {
      showPromptVersionDialog,
      allPrompts: { subscribe: allPrompts.subscribe },
      previewedPrompt
    },
    deletePrompt,
    refreshPrompts,
    updatePromptDescription,
    onPromptSelected,
    loadPreview
  });
}

export { getPromptManager, initPromptManager };
