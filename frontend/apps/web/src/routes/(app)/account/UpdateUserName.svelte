<!--
  When using an external IDP the user's changes to their name will be overwritten on the next login.
  This interface makes only sense in cases where the external IDP does not dictate the user's name,
  e.g. when using username and password login.
-->

<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  const { updateUserInfo } = getAppContext();

  const firstNameId = useId();
  const lastNameId = useId();
  const displayNameId = useId();

  export let firstName: string;
  export let lastName: string;
  export let displayName: string;

  // Needs to be defined as let first to not start out as "undefined"
  let displayNamePlaceholder = firstName + " " + lastName;
  $: displayNamePlaceholder = firstName + " " + lastName;

  // This check requires the placeholder to already be defined
  if (displayName === displayNamePlaceholder) {
    // The idea here is that we want the placeholder to be reactive, not the value
    displayName = "";
  }

  async function updateUser() {
    if (firstName === "" || lastName === "") return;

    try {
      await updateUserInfo({ firstName, lastName, displayName });
      isOpen = false;
    } catch (e) {
      toastError(e, m.error_updating_user_info());
    }
  }

  let isOpen = false;
</script>

<Dialog.Root bind:open={isOpen}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline">{m.change_your_name()}</Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form class="contents" on:submit|preventDefault={updateUser}>
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.change_your_name()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <Field.Field
            class="border-dimmer hover:bg-hover-dimmer justify-between border-b px-4 py-4"
          >
            <Field.Label for={firstNameId}>
              {m.first_name()}
              <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
            </Field.Label>
            <Input
              id={firstNameId}
              bind:value={firstName}
              maxlength={200}
              type="text"
              required
              aria-describedby={`${firstNameId}-description`}
            />
            <Field.Description id={`${firstNameId}-description`}>
              {m.first_name_description()}
            </Field.Description>
          </Field.Field>

          <Field.Field class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4">
            <Field.Label for={lastNameId}>
              {m.last_name()}
              <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
            </Field.Label>
            <Input id={lastNameId} bind:value={lastName} required maxlength={200} type="text" />
          </Field.Field>

          <Field.Field class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4">
            <Field.Label for={displayNameId}>{m.full_name()}</Field.Label>
            <Input
              id={displayNameId}
              bind:value={displayName}
              placeholder={displayNamePlaceholder}
              maxlength={200}
              type="text"
              aria-describedby={`${displayNameId}-description`}
            />
            <Field.Description id={`${displayNameId}-description`}>
              {m.full_name_description()}
            </Field.Description>
          </Field.Field>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button type="submit">{m.save_changes()}</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
