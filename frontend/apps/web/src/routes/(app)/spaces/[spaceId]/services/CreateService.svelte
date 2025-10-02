<script lang="ts">
  import { goto } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button, Dialog, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const intric = getIntric();

  let newServiceName = "";
  let openServiceAfterCreation = true;
  let isProcessing = false;
  async function createService() {
    if (newServiceName === "") return;
    isProcessing = true;

    try {
      const service = await intric.services.create({
        spaceId: $currentSpace.id,
        name: newServiceName
      });

      refreshCurrentSpace();
      $showCreateDialog = false;
      newServiceName = "";
      if (openServiceAfterCreation) {
        goto(`/spaces/${$currentSpace.routeId}/services/${service.id}?tab=edit`);
      }
    } catch (e) {
      alert(m.error_creating_new_service());
      console.error(e);
    }
    isProcessing = false;
  }

  let showCreateDialog: Dialog.OpenState;
</script>

<Dialog.Root alert bind:isOpen={showCreateDialog}>
  <Dialog.Trigger asFragment let:trigger>
    <Button is={trigger} variant="primary">{m.create_service()}</Button>
  </Dialog.Trigger>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.create_a_new_service()}</Dialog.Title>

    <Dialog.Section>
      {#if $currentSpace.completion_models.length < 1}
        <p
          class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
        >
          <span class="font-bold">{m.warning()}:</span>
          {m.completion_models_warning_service()}
        </p>
        <div class="border-default border-b"></div>
      {/if}
      <Input.Text
        bind:value={newServiceName}
        label={m.name()}
        required
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
      ></Input.Text>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Input.Switch bind:value={openServiceAfterCreation} class="flex-row-reverse p-2"
        >{m.open_service_editor_after_creation()}</Input.Switch
      >
      <div class="flex-grow"></div>
      <Button is={close}>{m.cancel()}</Button>
      <Button
        variant="primary"
        on:click={createService}
        disabled={isProcessing || $currentSpace.completion_models.length === 0}
        >{isProcessing ? m.creating() : m.create_service()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
