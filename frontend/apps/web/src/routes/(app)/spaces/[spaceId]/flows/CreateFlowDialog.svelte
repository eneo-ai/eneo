<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getFlowsManager } from "$lib/features/flows/FlowsManager";
  import { EneoError } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    open?: boolean;
  }

  let { open = $bindable(false) }: Props = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
  const flowsManager = getFlowsManager();

  let newFlowName = $state("");
  let createError = $state<string | null>(null);
  let isCreating = $state(false);

  function reset() {
    newFlowName = "";
    createError = null;
    isCreating = false;
  }

  function openDialog() {
    reset();
    open = true;
  }

  async function createManually() {
    const name = newFlowName.trim();
    if (!name || isCreating) return;
    isCreating = true;
    createError = null;
    try {
      const created = await flowsManager.createFlow(name);
      open = false;
      if (created.id) {
        goto(resolve(`/spaces/${$currentSpace.routeId}/flows/${created.id}`));
      }
    } catch (error) {
      createError = error instanceof EneoError ? error.getReadableMessage() : String(error);
    } finally {
      isCreating = false;
    }
  }
</script>

<Button variant="default" onclick={openDialog}>
  {m.flow_create_button()}
</Button>

<Dialog.Root
  bind:open
  onOpenChange={(next) => {
    if (next) reset();
  }}
>
  <Dialog.Content class="w-[calc(100%-1.5rem)] !max-w-[33rem] gap-0 overflow-hidden !p-0">
    <div class="px-6 pt-6">
      <Dialog.Title class="text-lg font-bold tracking-tight">
        {m.flow_create_dialog_title()}
      </Dialog.Title>
      <Dialog.Description class="text-secondary mt-1.5 text-sm text-pretty">
        {m.flow_create_dialog_description()}
      </Dialog.Description>
    </div>

    <form
      class="flex flex-col gap-2 px-6 pt-4"
      onsubmit={(event) => {
        event.preventDefault();
        void createManually();
      }}
    >
      <label for="flow-name-input" class="text-sm font-medium">{m.name()}</label>
      <Input
        id="flow-name-input"
        bind:value={newFlowName}
        placeholder={m.flow_create_name_placeholder()}
        class="max-sm:h-[44px]"
        required
      />
      <p class="text-secondary text-xs">{m.flow_create_path_manual_hint()}</p>
      {#if createError}
        <p
          class="text-negative-stronger bg-negative-dimmer rounded-lg px-3 py-2 text-sm"
          role="alert"
        >
          {createError}
        </p>
      {/if}
    </form>

    <Dialog.Footer
      class="border-dimmer mx-0 mt-4 mb-0 flex-row flex-wrap items-center gap-2.5 border-t bg-transparent px-6 py-3.5 sm:justify-start"
    >
      <span class="text-secondary text-sm">{m.flow_create_dialog_footnote()}</span>
      <div class="ml-auto flex items-center gap-2 max-sm:ml-0 max-sm:w-full max-sm:justify-end">
        <Button variant="outline" class="max-sm:h-[44px]" onclick={() => (open = false)}>
          {m.cancel()}
        </Button>
        <Button
          variant="default"
          class="max-sm:h-[44px]"
          disabled={!newFlowName.trim() || isCreating}
          onclick={createManually}
        >
          {isCreating ? m.flow_create_path_manual_creating() : m.flow_create_path_manual_action()}
        </Button>
      </div>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
