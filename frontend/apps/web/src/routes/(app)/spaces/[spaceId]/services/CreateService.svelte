<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
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
      showCreateDialog = false;
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

  let showCreateDialog = false;
</script>

<AlertDialog.Root bind:open={showCreateDialog}>
  <AlertDialog.Trigger>
    {#snippet child({ props })}
      <Button {...props}>{m.create_service()}</Button>
    {/snippet}
  </AlertDialog.Trigger>
  <AlertDialog.Content class={dialogLayout.content("medium")}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        createService();
      }}
    >
      <AlertDialog.Header class={dialogLayout.header}>
        <AlertDialog.Title>{m.create_a_new_service()}</AlertDialog.Title>
      </AlertDialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
            <Field.Label for={nameId}>
              {m.name()}
              <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
            </Field.Label>
            <Input id={nameId} bind:value={newServiceName} required />
          </Field.Field>
        </div>
      </div>

      <AlertDialog.Footer class={dialogLayout.footer}>
        <Field.Field orientation="horizontal" class="w-auto sm:mr-auto">
          <Switch id={openAfterId} bind:checked={openServiceAfterCreation} />
          <Field.Label for={openAfterId}>{m.open_service_editor_after_creation()}</Field.Label>
        </Field.Field>
        <AlertDialog.Cancel type="button">{m.cancel()}</AlertDialog.Cancel>
        <Button type="submit" disabled={isProcessing}
          >{isProcessing ? m.creating() : m.create_service()}</Button
        >
      </AlertDialog.Footer>
    </form>
  </AlertDialog.Content>
</AlertDialog.Root>
