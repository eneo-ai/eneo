<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts" generics="T extends { id: string }">
  import { IconSearch } from "@eneo/icons/search";
  import type { SpaceRole } from "@eneo/eneo-js";
  import { tick, type Snippet } from "svelte";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    open?: boolean;
    /** The picker's search text; the caller filters `items` with it. */
    filter?: string;
    triggerLabel: string;
    title: string;
    fieldLabel: string;
    searchPlaceholder: string;
    submitLabel: string;
    errorContext: string;
    emptyMessage: string;
    items: T[];
    /** Items already in the space; shown but not selectable. */
    addedIds: string[];
    getLabel: (item: T) => string;
    onAdd: (item: T, role: SpaceRole["value"]) => Promise<unknown>;
    row: Snippet<[item: T, added: boolean]>;
    /** Rendered after the items, e.g. a "load more" command item. */
    listEnd?: Snippet;
  };

  let {
    open = $bindable(false),
    filter = $bindable(""),
    triggerLabel,
    title,
    fieldLabel,
    searchPlaceholder,
    submitLabel,
    errorContext,
    emptyMessage,
    items,
    addedIds,
    getLabel,
    onAdd,
    row,
    listEnd
  }: Props = $props();

  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  const uid = $props.id();
  let selectedRole = $state.raw($currentSpace.available_roles[0]);
  let selected = $state.raw<T | undefined>();
  let pickerOpen = $state(false);
  let pickerTrigger = $state<HTMLButtonElement | null>(null);

  function select(item: T) {
    selected = item;
    pickerOpen = false;
    filter = "";
    void tick().then(() => pickerTrigger?.focus());
  }

  const add = createAsyncState(async () => {
    if (!selected) return;
    try {
      await onAdd(selected, selectedRole.value);
      refreshCurrentSpace();
      open = false;
      selected = undefined;
    } catch (e) {
      toastError(e, errorContext);
      console.error(e);
    }
  });
</script>

<Dialog.Root bind:open>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props}>{triggerLabel}</Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        add();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{title}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <div class="flex items-end gap-4 p-4">
            <Field.Field class="flex-grow">
              <Field.Label id={`${uid}-picker-label`} for={`${uid}-picker`}
                >{fieldLabel}</Field.Label
              >
              <Popover.Root bind:open={pickerOpen}>
                <Popover.Trigger>
                  {#snippet child({ props })}
                    <button
                      {...props}
                      bind:this={pickerTrigger}
                      id={`${uid}-picker`}
                      aria-labelledby={`${uid}-picker-label ${uid}-picker`}
                      type="button"
                      class={buttonVariants({
                        variant: "outline",
                        class: "w-full justify-between font-normal"
                      })}
                    >
                      <span class="truncate" class:text-muted={!selected}>
                        {selected ? getLabel(selected) : searchPlaceholder}
                      </span>
                      <IconSearch />
                    </button>
                  {/snippet}
                </Popover.Trigger>
                <Popover.Content align="start" class="w-(--bits-popover-anchor-width) p-0">
                  <Command.Root shouldFilter={false}>
                    <Command.Input bind:value={filter} placeholder={searchPlaceholder} />
                    <Command.List>
                      {#each items as item (item.id)}
                        {@const added = addedIds.includes(item.id)}
                        <Command.Item
                          value={item.id}
                          disabled={added}
                          onSelect={() => select(item)}
                        >
                          {@render row(item, added)}
                        </Command.Item>
                      {:else}
                        <p class="text-secondary px-2 py-1.5 text-sm">{emptyMessage}</p>
                      {/each}
                      {@render listEnd?.()}
                    </Command.List>
                  </Command.Root>
                </Popover.Content>
              </Popover.Root>
            </Field.Field>

            <Field.Field class="w-1/3">
              <Field.Label for={`${uid}-role`}>{m.role()}</Field.Label>
              <Select.Root
                type="single"
                value={selectedRole.value}
                onValueChange={(value) => {
                  selectedRole =
                    $currentSpace.available_roles.find((role) => role.value === value) ??
                    selectedRole;
                }}
              >
                <Select.Trigger id={`${uid}-role`} class="w-full"
                  >{selectedRole.label}</Select.Trigger
                >
                <Select.Content>
                  {#each $currentSpace.available_roles as role (role.value)}
                    <Select.Item value={role.value} label={role.label}>{role.label}</Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </Field.Field>
          </div>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button type="submit" disabled={!selected || add.isLoading}>
          {add.isLoading ? m.adding() : submitLabel}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
