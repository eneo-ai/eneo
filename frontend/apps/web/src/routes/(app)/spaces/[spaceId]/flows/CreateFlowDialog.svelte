<script lang="ts">
  import { goto } from "$app/navigation";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getFlowsManager } from "$lib/features/flows/FlowsManager";
  import { IconWorkflow } from "@intric/icons/workflow";
  import { IntricError } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const flowsManager = getFlowsManager();
  const showDialog = writable(false);

  let newFlowName = "";
  let openAfterCreation = true;

  async function createFlow() {
    try {
      const created = await flowsManager.createFlow(newFlowName);
      if (openAfterCreation && created.id) {
        goto(`/spaces/${$currentSpace.routeId}/flows/${created.id}`);
      }
      newFlowName = "";
      $showDialog = false;
    } catch (error) {
      const message = error instanceof IntricError ? error.getReadableMessage() : String(error);
      alert(message);
    }
  }
</script>

<Button variant="primary" onclick={() => ($showDialog = true)}>
  <IconWorkflow size="sm" />
  {m.flow_create()}
</Button>

<Dialog.Root openController={showDialog}>
  <Dialog.Content width="dynamic">
    <Dialog.Section class="relative mt-2 -mb-0.5">
      <div class="border-default flex w-full flex-col px-10 pt-12 pb-10">
        <h3 class="px-4 pb-1 text-2xl font-extrabold">{m.flow_create()}</h3>
        <p class="text-secondary max-w-[60ch] pr-36 pl-4">
          {m.flow_empty_description()}
        </p>
        <div class="border-dimmer mt-14 mb-4 border-t"></div>
        <div class="flex flex-col gap-1 pt-6 pb-4">
          <span class="px-4 pb-1 text-lg font-medium">{m.name()}</span>
          <Input.Text
            bind:value={newFlowName}
            hiddenLabel
            inputClass="!text-lg !py-6 !px-4"
            placeholder={m.flow_create_name_placeholder()}
            required>{m.name()}</Input.Text
          >
        </div>
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Input.Switch bind:value={openAfterCreation} class="flex-row-reverse p-2">
        Open editor after creation
      </Input.Switch>
      <div class="flex-grow"></div>
      <Button is={close}>{m.cancel()}</Button>
      <Button is={close} onclick={createFlow} variant="primary">{m.flow_create()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
