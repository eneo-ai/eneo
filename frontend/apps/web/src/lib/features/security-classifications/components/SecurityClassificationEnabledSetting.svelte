<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog } from "@eneo/ui";
  import { writable } from "svelte/store";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import { toastError } from "$lib/core/errors";
  import { Settings } from "$lib/components/layout";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";

  const uid = $props.id();
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
      toastError(e);
    }
  });

  const disable = createAsyncState(async () => {
    try {
      await security.disable();
      $showDisableDialog = false;
    } catch (e) {
      toastError(e);
    }
  });
</script>

<Settings.Row
  title={m.security_classification()}
  description={m.enable_security_description()}
  let:aria
>
  <div class="border-default flex h-14 border-b py-2">
    <RadioGroup.Root
      value={isEnabled ? "on" : "off"}
      onValueChange={(v) => {
        const next = v === "on";
        onValueChange({ current: isEnabled, next });
        isEnabled = next;
      }}
      class="grid w-full grid-cols-2 gap-2"
      {...aria}
    >
      <Field.Label for={`${uid}-on`} class="font-normal">
        <Field.Field orientation="horizontal">
          <RadioGroup.Item value="on" id={`${uid}-on`} />
          <span>{m.enabled()}</span>
        </Field.Field>
      </Field.Label>
      <Field.Label for={`${uid}-off`} class="font-normal">
        <Field.Field orientation="horizontal">
          <RadioGroup.Item value="off" id={`${uid}-off`} />
          <span>{m.disabled()}</span>
        </Field.Field>
      </Field.Label>
    </RadioGroup.Root>
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
      <Button variant="destructive" onclick={disable} disabled={disable.isLoading}
        >{m.disable()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
