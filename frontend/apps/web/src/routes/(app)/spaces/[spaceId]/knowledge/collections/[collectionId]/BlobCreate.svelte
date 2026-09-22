<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { type Group } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  type Props = {
    disabled?: boolean;
    collection: Group;
  };

  let { disabled = false, collection }: Props = $props();
  const id = $props.id();
  const eneo = getEneo();
  const { refreshCurrentSpace } = getSpacesManager();

  let open = $state(false);
  let title = $state("");
  let text = $state("");
  let isUploading = $state(false);

  async function uploadText(event: SubmitEvent) {
    event.preventDefault();
    if (isUploading || title === "" || text === "") {
      return;
    }

    try {
      isUploading = true;
      await eneo.infoBlobs.create({ group_id: collection.id, text, metadata: { title } });
      refreshCurrentSpace();
      invalidate("blobs:list");
      open = false;
      text = title = "";
    } catch (e) {
      toastError(e);
    } finally {
      isUploading = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} {disabled}>{m.add_text()}</Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content
    class="max-h-[85vh] overflow-y-auto sm:max-w-2xl"
    closeLabel={m.close()}
    showCloseButton={!isUploading}
    escapeKeydownBehavior={isUploading ? "ignore" : "close"}
    interactOutsideBehavior={isUploading ? "ignore" : "close"}
  >
    <Dialog.Header>
      <Dialog.Title>{m.add_text()}</Dialog.Title>
      <Dialog.Description>{collection.name}</Dialog.Description>
    </Dialog.Header>

    <form onsubmit={uploadText} class="flex flex-col gap-4" aria-busy={isUploading}>
      <div class="flex flex-col gap-2">
        <Label for={`${id}-title`}>{m.title()}</Label>
        <Input id={`${id}-title`} bind:value={title} required disabled={isUploading} />
      </div>

      <div class="flex flex-col gap-2">
        <Label for={`${id}-text`}>{m.content()}</Label>
        <Textarea
          id={`${id}-text`}
          bind:value={text}
          required
          rows={15}
          disabled={isUploading}
          class="field-sizing-fixed max-h-[50vh] min-h-40 resize-y"
        />
      </div>

      <Dialog.Footer>
        <Dialog.Close>
          {#snippet child({ props })}
            <Button {...props} variant="outline" disabled={isUploading}>{m.cancel()}</Button>
          {/snippet}
        </Dialog.Close>
        <Button type="submit" disabled={isUploading}>
          {isUploading ? m.submitting() : m.submit()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
