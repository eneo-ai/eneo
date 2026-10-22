<!--
    Copyright (c) 2026 Sundsvalls Kommun
-->

<script lang="ts">
  import { IconPlus } from "@eneo/icons/plus";
  import type { Assistant } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";

  type Specialist = NonNullable<Assistant["specialists"]>[number];
  type Props = {
    addSpecialist: (specialist: Specialist) => void;
    availableSpecialists: Specialist[];
  };

  const { addSpecialist, availableSpecialists }: Props = $props();
  const uid = $props.id();

  let selected = $state<Specialist | undefined>();
  let user_description = $state("");
  let isOpen = $state(false);

  const selectedHandle = $derived(
    availableSpecialists.find(({ id }) => id === selected?.id)?.handle
  );
</script>

<Dialog.Root bind:open={isOpen}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline" class="h-12"
        ><IconPlus></IconPlus>{m.add_specialist()}</Button
      >
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.add_specialist_title()}</Dialog.Title>
    </Dialog.Header>
    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
          <Field.Label for={`${uid}-specialist`}>{m.choose_a_specialist_to_add()}</Field.Label>
          <Select.Root
            type="single"
            value={selected?.id ?? ""}
            onValueChange={(id) =>
              (selected =
                availableSpecialists.find((specialist) => specialist.id === id) ?? selected)}
          >
            <Select.Trigger id={`${uid}-specialist`} class="w-full">
              {selectedHandle ?? m.ui_select_placeholder()}
            </Select.Trigger>
            <Select.Content>
              {#each availableSpecialists as specialist (specialist.id)}
                <Select.Item value={specialist.id} label={specialist.handle}>
                  {specialist.handle}
                </Select.Item>
              {:else}
                <Select.Item
                  value=""
                  disabled
                  label={m.ui_no_available_items({ resourceName: m.resource_assistants() })}
                >
                  {m.ui_no_available_items({ resourceName: m.resource_assistants() })}
                </Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </Field.Field>
        <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
          <Field.Label for={`${uid}-role`}>{m.specialist_role()}</Field.Label>
          <Textarea
            id={`${uid}-role`}
            bind:value={user_description}
            rows={4}
            placeholder={selected?.default_description ?? undefined}
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
        disabled={!selected}
        onclick={() => {
          if (!selected) return;
          const role = user_description.trim() === "" ? null : user_description;
          if (!role && !selected.default_description) {
            toast.warning(m.specialist_description_required());
            return;
          }
          addSpecialist({ ...selected, user_description: role });
          user_description = "";
          selected = undefined;
          isOpen = false;
        }}>{m.add_specialist()}</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
