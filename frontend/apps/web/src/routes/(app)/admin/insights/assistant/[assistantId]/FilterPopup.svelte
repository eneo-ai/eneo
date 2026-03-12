<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconFilter } from "@intric/icons/filter";
  import { Button, Dialog, Input } from "@intric/ui";
  import type { CalendarDate } from "@internationalized/date";
  import { m } from "$lib/paraglide/messages";

  export let includeFollowups: boolean;
  export let dateRange: { start: CalendarDate; end: CalendarDate };
  export let onUpdate:
    | ((
        includeFollowups: boolean,
        dateRange: { start: CalendarDate; end: CalendarDate }
      ) => Promise<void>)
    | undefined = undefined;

  let isOpen: Dialog.OpenState;
  let isUpdating = false;
  let updateError = "";

  async function update() {
    if (isUpdating) return;
    isUpdating = true;
    updateError = "";
    try {
      await onUpdate?.(includeFollowups, dateRange);
      $isOpen = false;
    } catch (error) {
      console.error(error);
      updateError = m.error_connecting_to_server();
    } finally {
      isUpdating = false;
    }
  }
</script>

<Dialog.Root bind:isOpen>
  <Dialog.Trigger asFragment let:trigger>
    <Button variant="primary" is={trigger}>
      <IconFilter />
      {m.settings()}</Button
    >
  </Dialog.Trigger>

  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.change_filter_settings()}</Dialog.Title>

    <Dialog.Section>
      <Input.DateRange
        bind:value={dateRange}
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
        >{m.included_timeframe()}</Input.DateRange
      >
      <Input.Switch
        bind:value={includeFollowups}
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
        >{m.include_follow_up_questions()}</Input.Switch
      >
    </Dialog.Section>
    {#if updateError}
      <p class="px-4 pt-2 text-sm text-red-700" role="alert">{updateError}</p>
    {/if}

    <Dialog.Controls let:close>
      <Button is={close} disabled={isUpdating}>{m.cancel()}</Button>

      <Button variant="primary" on:click={update} disabled={isUpdating}>
        {isUpdating ? m.loading() : m.update()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
