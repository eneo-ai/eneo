<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
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
  let showEnableDialog = $state(false);
  let showDisableDialog = $state(false);

  function onValueChange({ current, next }: { current: boolean; next: boolean }) {
    if (current !== next) {
      showEnableDialog = next;
      showDisableDialog = !next;
    }
  }

  function resetOnClose(open: boolean) {
    if (!open) isEnabled = security.isSecurityEnabled;
  }

  const enable = createAsyncState(async () => {
    try {
      await security.enable();
      showEnableDialog = false;
    } catch (e) {
      toastError(e);
    }
  });

  const disable = createAsyncState(async () => {
    try {
      await security.disable();
      showDisableDialog = false;
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

<Dialog.Root bind:open={showEnableDialog} onOpenChange={resetOnClose}>
  <Dialog.Content class={dialogLayout.content()} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.enable_security_classifications()}</Dialog.Title>
      <Dialog.Description>
        {m.enable_security_classifications_dialog_description()}
      </Dialog.Description>
    </Dialog.Header>

    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Button onclick={enable} disabled={enable.isLoading}>{m.enable()}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={showDisableDialog} onOpenChange={resetOnClose}>
  <Dialog.Content class={dialogLayout.content()} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.disable_security_classifications()}</Dialog.Title>
      <Dialog.Description>
        {m.disable_security_classifications_dialog_description()}
      </Dialog.Description>
    </Dialog.Header>

    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Button variant="destructive" onclick={disable} disabled={disable.isLoading}
        >{m.disable()}</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
