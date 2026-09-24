<script lang="ts">
  import { useId } from "bits-ui";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import Hint from "$lib/components/Hint.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";

  type Props = {
    open?: boolean;
    title: string;
    submitLabel: string;
    /** Always shown under the destination picker. */
    hint?: string;
    /** Adds a switch to move the resource's own knowledge along; `hint` is shown while it is on. */
    resourcesOption?: { label: string; hint: string };
    /** The dialog closes when this resolves; when it throws, it stays open and shows the error. */
    onMove: (targetSpace: { id: string }, options: { moveResources: boolean }) => unknown;
  };

  let {
    open = $bindable(false),
    title,
    submitLabel,
    hint,
    resourcesOption,
    onMove
  }: Props = $props();

  const {
    state: { currentSpace, accessibleSpaces }
  } = getSpacesManager();

  const destinationId = useId();
  const resourcesId = useId();

  let destinationSpaceId = $state("");
  let moveResources = $state(false);
  let pending = $state(false);

  const targets = $derived(
    $accessibleSpaces
      .filter((space) => space.id !== $currentSpace.id)
      .map((space) => ({ id: space.id, name: space.name }))
  );
  const destinationName = $derived(targets.find((space) => space.id === destinationSpaceId)?.name);

  async function move() {
    if (pending || !destinationSpaceId) return;
    pending = true;
    try {
      await onMove({ id: destinationSpaceId }, { moveResources });
      open = false;
    } catch (error) {
      toastError(error);
    } finally {
      pending = false;
    }
  }
</script>

<Dialog.Root
  bind:open={
    () => open,
    (value) => {
      if (!pending) open = value;
    }
  }
>
  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        move();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{title}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <Field.Field
            class={cn("hover:bg-hover-dimmer rounded-t-md px-4", hint ? "pt-4" : "py-4")}
          >
            <Field.Label for={destinationId}>{m.destination()}</Field.Label>
            <Select.Root type="single" name="destination" required bind:value={destinationSpaceId}>
              <Select.Trigger id={destinationId} class="w-full">
                {destinationName ?? m.ui_select_placeholder()}
              </Select.Trigger>
              <Select.Content>
                {#each targets as space (space.id)}
                  <Select.Item value={space.id} label={space.name}>{space.name}</Select.Item>
                {:else}
                  <Select.Item
                    value=""
                    disabled
                    label={m.ui_no_available_items({ resourceName: m.resource_spaces() })}
                  >
                    {m.ui_no_available_items({ resourceName: m.resource_spaces() })}
                  </Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </Field.Field>
          {#if hint}
            <Hint class="mx-4 mt-1.5 mb-4">{hint}</Hint>
          {/if}
          {#if resourcesOption}
            <Field.Field orientation="horizontal" class="hover:bg-hover-dimmer border-t px-4 py-4">
              <Field.Label for={resourcesId}>{resourcesOption.label}</Field.Label>
              <Switch id={resourcesId} bind:checked={moveResources} />
            </Field.Field>
            {#if moveResources}
              <Hint class="mx-4 mb-3">{resourcesOption.hint}</Hint>
            {/if}
          {/if}
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close
          aria-disabled={pending}
          class={cn(
            buttonVariants({ variant: "outline" }),
            pending && "pointer-events-none opacity-50"
          )}>{m.cancel()}</Dialog.Close
        >
        <Button type="submit" variant="destructive" disabled={pending} aria-busy={pending}>
          {pending ? m.moving() : submitLabel}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
