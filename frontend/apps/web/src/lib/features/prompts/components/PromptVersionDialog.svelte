<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconHistory } from "@eneo/icons/history";
  import { Dialog, Button, Tooltip } from "@eneo/ui";
  import PromptTable from "./PromptTable.svelte";
  import PromptPreview from "./PromptPreview.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { initPromptManager } from "../PromptManager";
  import type { Prompt, PromptSparse } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";

  export let title = m.prompt_history();
  export let onPromptSelected: (prompt: Prompt) => void;
  export let loadPromptVersionHistory: () => Promise<PromptSparse[]>;

  const eneo = getEneo();

  const {
    state: { showPromptVersionDialog }
  } = initPromptManager({
    eneo,
    onPromptSelected,
    loadPromptVersionHistory
  });
</script>

<Dialog.Root openController={showPromptVersionDialog}>
  <Dialog.Trigger asFragment let:trigger>
    <Tooltip text={m.show_prompt_history()}>
      <Button is={trigger} padding="icon"><IconHistory /></Button>
    </Tooltip>
  </Dialog.Trigger>
  <Dialog.Content width="large">
    <Dialog.Title>{title}</Dialog.Title>
    <div
      class="relative grid max-h-[80vh] min-h-[70vh] grid-cols-1 grid-rows-2 gap-4 pb-2.5 lg:grid-cols-2 lg:grid-rows-1"
    >
      <PromptTable></PromptTable>
      <PromptPreview></PromptPreview>
    </div>
  </Dialog.Content>
</Dialog.Root>
