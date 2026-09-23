<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button } from "$lib/components/ui/button/index.js";
  import NameDialog from "$lib/components/NameDialog.svelte";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const eneo = getEneo();

  let openServiceAfterCreation = true;
  const openAfterId = useId();

  async function createService(name: string) {
    const service = await eneo.services.create({
      spaceId: $currentSpace.id,
      name
    });

    refreshCurrentSpace();
    if (openServiceAfterCreation) {
      goto(resolve(`/spaces/${$currentSpace.routeId}/services/${service.id}?tab=edit`));
    }
  }
</script>

<NameDialog
  title={m.create_a_new_service()}
  label={m.name()}
  submitLabel={m.create_service()}
  pendingLabel={m.creating()}
  width="medium"
  errorContext={m.error_creating_new_service()}
  onSubmit={createService}
>
  {#snippet trigger({ props })}
    <Button {...props}>{m.create_service()}</Button>
  {/snippet}
  {#snippet footerExtra()}
    <Field.Field orientation="horizontal">
      <Switch id={openAfterId} bind:checked={openServiceAfterCreation} />
      <Field.Label for={openAfterId}>{m.open_service_editor_after_creation()}</Field.Label>
    </Field.Field>
  {/snippet}
</NameDialog>
