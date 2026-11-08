<!--
    Copyright (c) 2026 Sundsvalls Kommun
-->

<script lang="ts">
  import { IconCog } from "@eneo/icons/cog";
  import type { Assistant } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";

  type Specialist = NonNullable<Assistant["specialists"]>[number];
  type Props = {
    updateSpecialist: (specialist: Specialist) => void;
    specialist: Specialist;
  };

  const { specialist, updateSpecialist }: Props = $props();
  const uid = $props.id();

  let descriptionProxy = $derived.by(() => {
    let value = $state(specialist.user_description ?? "");
    return { value };
  });

  let isOpen = $state(false);
</script>

<Dialog.Root bind:open={isOpen}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline" size="icon" aria-label={m.edit_specialist()}
        ><IconCog></IconCog></Button
      >
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.edit_specialist()}</Dialog.Title>
    </Dialog.Header>
    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
          <Field.Label for={`${uid}-handle`}>{m.assistant()}</Field.Label>
          <Input
            id={`${uid}-handle`}
            value={specialist.handle}
            disabled
            class="text-secondary pointer-events-none"
          />
        </Field.Field>
        <Field.Field class="border-default hover:bg-hover-dimmer px-4 py-4">
          <Field.Label for={`${uid}-role`}>{m.specialist_role()}</Field.Label>
          <Textarea
            id={`${uid}-role`}
            bind:value={descriptionProxy.value}
            rows={4}
            placeholder={specialist.default_description ?? undefined}
            aria-describedby={`${uid}-role-description`}
          />
          <Field.Description id={`${uid}-role-description`}>
            {m.specialist_role_help()}
          </Field.Description>
        </Field.Field>
      </div>
    </div>
    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Button
        onclick={() => {
          const role = descriptionProxy.value.trim() === "" ? null : descriptionProxy.value;
          if (!role && !specialist.default_description) {
            toast.warning(m.specialist_description_required());
            return;
          }
          updateSpecialist({ ...specialist, user_description: role });
          isOpen = false;
        }}>{m.accept_changes()}</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
