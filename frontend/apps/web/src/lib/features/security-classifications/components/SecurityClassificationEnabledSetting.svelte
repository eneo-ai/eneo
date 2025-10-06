<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog, Input } from "@intric/ui";
  import { writable } from "svelte/store";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import { IntricError } from "@intric/intric-js";
  import { Settings } from "$lib/components/layout";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";

  const security = getSecurityClassificationService();

  let isEnabled = $derived(security.isSecurityEnabled);
  let showEnableDialog = writable(false);
  let showDisableDialog = writable(false);

  function onValueChange({ current, next }: { current: boolean; next: boolean }) {
    if (current !== next) {
      $showEnableDialog = next;
      $showDisableDialog = !next;
    }
  }

  const enable = createAsyncState(async () => {
    try {
      await security.enable();
      $showEnableDialog = false;
    } catch (e) {
      alert(e instanceof IntricError ? e.getReadableMessage() : String(e));
    }
  });

  const disable = createAsyncState(async () => {
    try {
      await security.disable();
      $showDisableDialog = false;
    } catch (e) {
      alert(e instanceof IntricError ? e.getReadableMessage() : String(e));
    }
  });
</script>

<Settings.Row
  title={m.security_classification()}
  description={m.enable_security_description()}
>
  <div class="border-default flex h-14 border-b py-2">
    <Input.RadioSwitch bind:value={isEnabled} sideEffect={onValueChange} labelTrue={m.enabled()} labelFalse={m.disabled()}></Input.RadioSwitch>
  </div>
</Settings.Row>

<Dialog.Root openController={showEnableDialog}>
  <Dialog.Content>
    <Dialog.Title>{m.enable_security_classifications()}</Dialog.Title>

    <Dialog.Description>
      {m.enable_security_classifications_dialog_description()}
    </Dialog.Description>

    <Dialog.Controls>
      <Button
        onclick={() => {
          isEnabled = security.isSecurityEnabled;
          $showEnableDialog = false;
        }}>{m.cancel()}</Button
      >
      <Button variant="primary" onclick={enable} disabled={enable.isLoading}>{m.enable()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root openController={showDisableDialog}>
  <Dialog.Content>
    <Dialog.Title>{m.disable_security_classifications()}</Dialog.Title>

    <Dialog.Description>
      {m.disable_security_classifications_dialog_description()}
    </Dialog.Description>

    <Dialog.Controls>
      <Button
        onclick={() => {
          isEnabled = security.isSecurityEnabled;
          $showDisableDialog = false;
        }}>{m.cancel()}</Button
      >
      <Button variant="destructive" onclick={disable} disabled={disable.isLoading}>{m.disable()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
