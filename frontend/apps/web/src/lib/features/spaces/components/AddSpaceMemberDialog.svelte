<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts" generics="T extends { id: string }">
  import { IconSearch } from "@eneo/icons/search";
  import type { SpaceRoleValue } from "@eneo/eneo-js";
  import { CircleAlert } from "@lucide/svelte";
  import { tick, untrack, type Snippet } from "svelte";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { Button, buttonVariants, type ButtonVariant } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import { lowestRole, sortRolesAscending, spaceRoleLabel } from "../roles";

  type Props = {
    open?: boolean;
    /** The picker's search text; the caller filters `items` with it. */
    filter?: string;
    triggerLabel: string;
    triggerVariant?: ButtonVariant;
    title: string;
    fieldLabel: string;
    searchPlaceholder: string;
    submitLabel: string;
    /** Prefixes a failure shown in the dialog. */
    errorContext: string;
    emptyMessage: string;
    items: T[];
    /** Items that cannot be picked, e.g. members already in the space; shown but disabled. */
    addedIds: string[];
    /** The roles a new member may get; the lowest is preselected. */
    roles: readonly SpaceRoleValue[];
    getLabel: (item: T) => string;
    /** Saves the member. The dialog stays open and shows the error if it rejects. */
    onAdd: (item: T, role: SpaceRoleValue) => Promise<unknown>;
    /** Runs after a member was added and the dialog closed, e.g. to reload the members. */
    onAdded?: () => unknown;
    row: Snippet<[item: T, added: boolean]>;
    /** Rendered after the items, e.g. a "load more" command item. */
    listEnd?: Snippet;
  };

  let {
    open = $bindable(false),
    filter = $bindable(""),
    triggerLabel,
    triggerVariant = "default",
    title,
    fieldLabel,
    searchPlaceholder,
    submitLabel,
    errorContext,
    emptyMessage,
    items,
    addedIds,
    roles,
    getLabel,
    onAdd,
    onAdded,
    row,
    listEnd
  }: Props = $props();

  const uid = $props.id();
  const options = $derived(sortRolesAscending(roles));
  let selectedRole = $state<SpaceRoleValue | undefined>();
  const role = $derived(
    selectedRole && roles.includes(selectedRole) ? selectedRole : lowestRole(roles)
  );
  let selected = $state.raw<T | undefined>();
  let pickerOpen = $state(false);
  let pickerTrigger = $state<HTMLButtonElement | null>(null);
  let error = $state<string | null>(null);

  // Each time it opens: nobody picked, the lowest role, no old error.
  $effect.pre(() => {
    if (!open) return;
    untrack(() => {
      selected = undefined;
      selectedRole = undefined;
      error = null;
    });
  });

  function select(item: T) {
    selected = item;
    error = null;
    pickerOpen = false;
    filter = "";
    void tick().then(() => pickerTrigger?.focus());
  }

  const add = createAsyncState(async () => {
    if (!selected || !role) return;
    error = null;
    try {
      await onAdd(selected, role);
    } catch (e) {
      error = `${errorContext} ${getErrorMessage(e)}`;
      return;
    }
    open = false;
    await onAdded?.();
  });
</script>

<Dialog.Root bind:open>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant={triggerVariant} class="max-md:min-h-11">{triggerLabel}</Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        if (!add.isLoading) void add();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{title}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <div class="flex flex-col gap-4 p-4 sm:flex-row sm:items-end">
            <Field.Field class="min-w-0 flex-grow">
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
                        class: "w-full justify-between font-normal max-md:min-h-11"
                      })}
                    >
                      <!-- Full-strength text: a muted placeholder falls below 4.5:1 on the dark outline surface. -->
                      <span class="truncate">
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

            <Field.Field class="sm:w-1/3">
              <Field.Label id={`${uid}-role-label`} for={`${uid}-role`}>{m.role()}</Field.Label>
              <Select.Root
                type="single"
                bind:value={() => role ?? "", (value) => (selectedRole = value as SpaceRoleValue)}
              >
                <Select.Trigger
                  id={`${uid}-role`}
                  aria-labelledby={`${uid}-role-label ${uid}-role-value`}
                  class="w-full max-md:min-h-11"
                >
                  <span id={`${uid}-role-value`}>{role ? spaceRoleLabel(role) : ""}</span>
                </Select.Trigger>
                <Select.Content>
                  {#each options as option (option)}
                    <Select.Item value={option} label={spaceRoleLabel(option)}>
                      {spaceRoleLabel(option)}
                    </Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </Field.Field>
          </div>
        </div>

        {#if error}
          <div
            role="alert"
            class="bg-negative-dimmer text-negative-stronger flex items-start gap-2 rounded-lg p-3 text-sm"
          >
            <CircleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p class="min-w-0">{error}</p>
          </div>
        {/if}
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline", class: "max-md:min-h-11" })}
          >{m.cancel()}</Dialog.Close
        >
        <!-- aria-disabled while saving: a focused button that becomes disabled drops focus. -->
        <Button
          type="submit"
          class={["max-md:min-h-11", add.isLoading && "pointer-events-none opacity-50"]}
          disabled={!selected}
          aria-disabled={add.isLoading}
          aria-busy={add.isLoading}
        >
          {add.isLoading ? m.adding() : submitLabel}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
