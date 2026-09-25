<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<!--
  A member's role in a space and the button that removes them. It only takes
  props, so the space's own members page and admin oversight share it: the
  caller decides which API to call and how to report a failure.
-->
<script lang="ts">
  import type { SpaceRoleValue } from "@eneo/eneo-js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { Trash2 } from "@lucide/svelte";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";
  import { sortRolesAscending, spaceRoleLabel } from "../roles";

  type Props = {
    /** The person's or group's name, which makes each control's name unique. */
    name: string;
    role: SpaceRoleValue;
    /** The roles the member may be given. */
    roles: readonly SpaceRoleValue[];
    /**
     * Refuses changing the role and removing, e.g. for the space's only
     * administrator. Both controls stay focusable and read out the reason.
     */
    disabled?: boolean;
    /** The id of the visible text that says why the controls are disabled. */
    disabledReasonId?: string;
    /** Saves the role. A rejection puts the previous role back, so report the error first. */
    onChangeRole: (role: SpaceRoleValue) => Promise<unknown>;
    /** Removes the member; the confirmation stays open and shows the error if it rejects. */
    onRemove: () => Promise<unknown>;
    removeTitle: string;
    removeDescription: string;
    /** Prefixes a removal failure shown in the confirmation. */
    removeErrorContext?: string;
    class?: string;
  };

  let {
    name,
    role,
    roles,
    disabled = false,
    disabledReasonId,
    onChangeRole,
    onRemove,
    removeTitle,
    removeDescription,
    removeErrorContext,
    class: className
  }: Props = $props();

  const uid = $props.id();
  const options = $derived(sortRolesAscending(roles));

  // Shows a new role straight away; the prop takes over again once the caller saves it.
  let shownRole = $derived(role);
  let changing = $state(false);
  let selectOpen = $state(false);
  let removeOpen = $state(false);

  async function change(next: SpaceRoleValue) {
    if (disabled || changing || next === shownRole) return;
    const previous = shownRole;
    shownRole = next;
    changing = true;
    try {
      await onChangeRole(next);
    } catch {
      shownRole = previous;
    } finally {
      changing = false;
    }
  }
</script>

<div class={cn("flex min-w-0 items-center gap-2", className)}>
  <span id={`${uid}-label`} class="sr-only">{m.admin_spaces_role_for({ name })}</span>
  <Select.Root
    type="single"
    bind:value={() => shownRole, (value) => void change(value as SpaceRoleValue)}
    bind:open={() => selectOpen, (value) => (selectOpen = value && !disabled && !changing)}
  >
    <Select.Trigger
      aria-labelledby={`${uid}-label ${uid}-value`}
      aria-disabled={disabled || undefined}
      aria-describedby={disabled ? disabledReasonId : undefined}
      aria-busy={changing || undefined}
      class={cn(
        "min-w-36 justify-between max-md:min-h-12 max-md:flex-1",
        disabled && "cursor-not-allowed opacity-60"
      )}
    >
      <span class="flex items-center gap-2">
        <span id={`${uid}-value`}>{spaceRoleLabel(shownRole)}</span>
        {#if changing}
          <IconLoadingSpinner class="size-4 animate-spin" aria-hidden="true" />
        {/if}
      </span>
    </Select.Trigger>
    <Select.Content>
      {#each options as option (option)}
        <Select.Item value={option} label={spaceRoleLabel(option)}>
          {spaceRoleLabel(option)}
        </Select.Item>
      {/each}
    </Select.Content>
  </Select.Root>

  <ConfirmDialog
    bind:open={() => removeOpen, (value) => (removeOpen = value && !disabled)}
    title={removeTitle}
    description={removeDescription}
    confirmLabel={m.remove()}
    pendingLabel={m.removing()}
    errorContext={removeErrorContext}
    errorDisplay="inline"
    onConfirm={onRemove}
  >
    {#snippet trigger({ props: triggerProps })}
      <Button
        {...triggerProps}
        variant="ghost"
        size="icon"
        class={cn(
          "text-secondary shrink-0 max-md:size-12",
          disabled ? "cursor-not-allowed opacity-60" : "hover:text-negative-stronger"
        )}
        aria-label={m.admin_spaces_remove_named({ name })}
        aria-disabled={disabled || undefined}
        aria-describedby={disabled ? disabledReasonId : undefined}
      >
        <Trash2 aria-hidden="true" />
      </Button>
    {/snippet}
  </ConfirmDialog>
</div>
