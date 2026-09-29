<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import type { UserGroup } from "@eneo/eneo-js";
  import { ChevronDown } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button";
  import * as Command from "$lib/components/ui/command";
  import * as Popover from "$lib/components/ui/popover";
  import * as Field from "$lib/components/ui/field";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  let {
    selectedGroups,
    userGroups,
    user,
    disabled = false,
    pending = $bindable(false),
    onChanged
  }: {
    selectedGroups: UserGroup[];
    userGroups: UserGroup[];
    user: { id: string };
    disabled?: boolean;
    pending?: boolean;
    onChanged: (groups: UserGroup[]) => void;
  } = $props();

  const eneo = getEneo();
  const id = $props.id();
  let open = $state(false);
  let selectedId = $state("");
  let trigger = $state<HTMLButtonElement | null>(null);
  const availableGroups = $derived(
    userGroups.filter((group) => !selectedGroups.some((selected) => selected.id === group.id))
  );
  const selectedGroup = $derived(availableGroups.find((group) => group.id === selectedId));
  const busy = $derived(disabled || pending);

  async function changeGroup(group: UserGroup, action: "add" | "remove") {
    if (busy) return;
    pending = true;
    try {
      const success =
        action === "add"
          ? await eneo.userGroups.addUser({ userGroup: group, user })
          : await eneo.userGroups.removeUser({ userGroup: group, user });
      if (success) {
        onChanged(
          action === "add"
            ? [...selectedGroups, group]
            : selectedGroups.filter((selected) => selected.id !== group.id)
        );
        selectedId = "";
        await invalidate("admin:users");
      }
    } catch (error) {
      toastError(error);
    } finally {
      pending = false;
    }
  }
</script>

<Field.Field class="border-border border-t pt-5" aria-busy={pending}>
  <Field.Label for={id}>{m.user_groups()}</Field.Label>
  <Field.Description id={`${id}-hint`}>{m.admin_user_groups_immediate_hint()}</Field.Description>
  <div class="flex items-center gap-2">
    <Popover.Root bind:open>
      <Popover.Trigger>
        {#snippet child({ props })}
          <Button
            {...props}
            bind:ref={trigger}
            {id}
            variant="outline"
            class="min-w-0 flex-1 justify-between"
            disabled={busy || availableGroups.length === 0}
            aria-describedby={`${id}-hint`}
          >
            <span class="truncate">{selectedGroup?.name ?? m.select_user_group()}</span>
            <ChevronDown class="size-4 shrink-0" />
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content class="w-[var(--bits-popover-anchor-width)] p-0">
        <Command.Root>
          <Command.Input placeholder={m.select_user_group()} aria-label={m.select_user_group()} />
          <Command.List>
            <Command.Empty>{m.no_results_found()}</Command.Empty>
            {#each availableGroups as group (group.id)}
              <Command.Item
                value={group.id}
                keywords={[group.name]}
                onSelect={() => {
                  selectedId = group.id;
                  open = false;
                  trigger?.focus();
                }}
              >
                {group.name}
              </Command.Item>
            {/each}
          </Command.List>
        </Command.Root>
      </Popover.Content>
    </Popover.Root>
    <Button
      disabled={busy || !selectedGroup}
      onclick={() => {
        if (selectedGroup) void changeGroup(selectedGroup, "add");
      }}>{m.assign()}</Button
    >
  </div>
  {#if selectedGroups.length > 0}
    <ul class="border-border divide-border divide-y rounded-lg border">
      {#each selectedGroups as group (group.id)}
        <li class="flex items-center justify-between gap-3 px-3 py-2">
          <span class="min-w-0 break-words">{group.name}</span>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            aria-label={m.admin_remove_user_group({ name: group.name })}
            onclick={() => changeGroup(group, "remove")}
          >
            {m.remove()}
          </Button>
        </li>
      {/each}
    </ul>
  {/if}
</Field.Field>
