<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button, Dialog } from "@eneo/ui";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const eneo = getEneo();

  let newServiceName = "";
  let openServiceAfterCreation = true;
  let isProcessing = false;
  const nameId = useId();
  const openAfterId = useId();

  async function createService() {
    if (newServiceName === "") return;
    isProcessing = true;

    try {
      const service = await eneo.services.create({
        spaceId: $currentSpace.id,
        name: newServiceName
      });

      refreshCurrentSpace();
      $showCreateDialog = false;
      newServiceName = "";
      if (openServiceAfterCreation) {
        goto(resolve(`/spaces/${$currentSpace.routeId}/services/${service.id}?tab=edit`));
      }
    } catch (e) {
      toastError(e, m.error_creating_new_service());
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
      <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
        <Field.Label for={nameId}>
          {m.name()}
          <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
        </Field.Label>
        <Input id={nameId} bind:value={newServiceName} required />
      </Field.Field>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Field.Field orientation="horizontal" class="w-auto p-2">
        <Switch id={openAfterId} bind:checked={openServiceAfterCreation} />
        <Field.Label for={openAfterId}>{m.open_service_editor_after_creation()}</Field.Label>
      </Field.Field>
      <div class="flex-grow"></div>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={createService} disabled={isProcessing}
        >{isProcessing ? m.creating() : m.create_service()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
