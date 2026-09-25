<!--
  A tenant administrator joins a shared space to reach its content: with a
  role no higher than needed and a written reason, both of which the space's
  members and the audit log will see.
-->
<script lang="ts">
  import type { AdminSpaceViewerMembership, SpaceRoleValue } from "@eneo/eneo-js";
  import {
    CircleAlert,
    DoorOpen,
    ExternalLink,
    Eye,
    ScrollText,
    ShieldCheck
  } from "@lucide/svelte";
  import { tick, untrack } from "svelte";
  import { invalidateAll } from "$app/navigation";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { toast } from "$lib/components/toast";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { docsUrl } from "$lib/core/docs";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { cn } from "$lib/utils.js";
  import { sortRolesAscending, spaceRoleDescription, spaceRoleLabel } from "../roles";
  import { formatList } from "$lib/core/formatting/formatList";
  import { reasonError } from "./reason";
  import ReasonField from "./ReasonField.svelte";

  type Props = {
    space: {
      id: string;
      name: string;
      security_classification?: { name: string; security_level: number } | null;
    };
    membership: AdminSpaceViewerMembership;
    /** The "Gå med i ytan…" button's look. */
    triggerVariant?: "default" | "outline";
    /**
     * Where focus goes after joining, since the button that opened the dialog
     * usually disappears with the change: e.g. the membership banner's heading.
     */
    focusAfterJoin?: () => HTMLElement | null | undefined;
  };

  let { space, membership, triggerVariant = "default", focusAfterJoin }: Props = $props();

  const eneo = getEneo();
  const uid = $props.id();
  let open = $state(false);

  const roles = $derived(sortRolesAscending(membership.joinable_roles));
  let chosen = $state<SpaceRoleValue | null>(null);
  // The lowest role is the default, so a higher one is always a deliberate choice.
  const role = $derived(chosen && roles.includes(chosen) ? chosen : roles[0]);

  let reason = $state("");
  // Checked from the first submit on, so the message goes away once the reason is long enough.
  let attempted = $state(false);
  const reasonMessage = $derived(attempted ? reasonError(reason) : null);
  let serverError = $state<string | null>(null);
  let pending = $state(false);
  let joined = false;
  let reasonInput = $state<HTMLTextAreaElement | null>(null);
  let content = $state<HTMLElement | null>(null);
  let errorAlert = $state<HTMLElement | null>(null);

  // Before the content renders, so the dialog opens on the default role and an empty reason.
  $effect.pre(() => {
    if (!open) return;
    untrack(() => {
      chosen = null;
      reason = "";
      attempted = false;
      serverError = null;
      joined = false;
    });
  });

  const groupNote = $derived(
    membership.group_role
      ? m.admin_spaces_join_group_note({
          role: spaceRoleLabel(membership.group_role),
          groups: formatList(membership.via_groups.map((group) => group.name))
        })
      : null
  );

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (pending || !role) return;
    serverError = null;
    attempted = true;
    if (reasonError(reason)) {
      await tick();
      reasonInput?.focus();
      return;
    }

    pending = true;
    try {
      await eneo.spaces.admin.join({ spaceId: space.id, role, reason });
    } catch (error) {
      serverError = getErrorMessage(error, m.admin_spaces_join_failed());
      await tick();
      errorAlert?.scrollIntoView({ block: "nearest" });
      return;
    } finally {
      pending = false;
    }

    joined = true;
    const joinedAs = role;
    open = false;
    await invalidateAll();
    toast.success(m.admin_spaces_join_done({ role: spaceRoleLabel(joinedAs), space: space.name }));
    await tick();
    focusAfterJoin?.()?.focus();
  }
</script>

<Dialog.Root
  bind:open={
    () => open,
    (value) => {
      if (!pending) open = value;
    }
  }
>
  {#if roles.length > 0}
    <Dialog.Trigger class={buttonVariants({ variant: triggerVariant, class: "max-md:min-h-11" })}>
      {m.admin_spaces_join_open()}
    </Dialog.Trigger>
  {/if}

  <Dialog.Content
    bind:ref={content}
    class={dialogLayout.content("medium")}
    closeLabel={m.close()}
    onOpenAutoFocus={(event) => {
      const radio =
        content?.querySelector<HTMLElement>('[role="radio"][data-state="checked"]') ??
        content?.querySelector<HTMLElement>('[role="radio"]');
      if (!radio) return;
      event.preventDefault();
      radio.focus();
    }}
    onCloseAutoFocus={(event) => {
      // The opener is usually gone once the page shows the membership.
      if (joined) event.preventDefault();
    }}
  >
    <form class="contents" novalidate onsubmit={submit}>
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title class="leading-snug">
          {m.admin_spaces_join_title({ space: space.name })}
        </Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <!-- In the scrolling body, so a phone keeps room for the form. -->
        <Dialog.Description class="text-primary flex flex-col gap-2 text-sm">
          {#if space.security_classification}
            <span class="flex items-start gap-2 font-medium">
              <ShieldCheck class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {m.admin_spaces_join_classified({
                classification: space.security_classification.name
              })}
            </span>
          {/if}
          <span>{m.admin_spaces_join_intro()}</span>
        </Dialog.Description>

        <ul class="border-default bg-secondary flex flex-col gap-2 rounded-lg border p-3 text-sm">
          <li class="flex items-start gap-2">
            <Eye class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {m.admin_spaces_join_bullet_visible()}
          </li>
          <li class="flex items-start gap-2">
            <ScrollText class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {m.admin_spaces_join_bullet_audit()}
          </li>
          <li class="flex items-start gap-2">
            <DoorOpen class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {m.admin_spaces_join_bullet_leave()}
          </li>
        </ul>

        <Field.Set class="gap-3">
          <Field.Legend id={`${uid}-role-legend`} variant="label" class="mb-0">
            {m.role()}
          </Field.Legend>
          <p id={`${uid}-role-hint`} class="text-secondary -mt-1 text-sm">
            {m.admin_spaces_join_role_hint()}
          </p>
          <RadioGroup.Root
            bind:value={() => role ?? "", (value) => (chosen = value as SpaceRoleValue)}
            aria-labelledby={`${uid}-role-legend`}
            aria-describedby={groupNote ? `${uid}-role-hint ${uid}-group-note` : `${uid}-role-hint`}
            class="gap-2"
          >
            {#each roles as option (option)}
              <div
                class="border-default has-data-[state=checked]:border-accent-default has-data-[state=checked]:bg-accent-dimmer flex items-start gap-3 rounded-lg border p-3"
              >
                <RadioGroup.Item
                  id={`${uid}-role-${option}`}
                  value={option}
                  aria-describedby={`${uid}-role-${option}-description`}
                  class="mt-0.5"
                />
                <div class="flex min-w-0 flex-col gap-1">
                  <Label for={`${uid}-role-${option}`} class="cursor-pointer">
                    {spaceRoleLabel(option)}
                  </Label>
                  <p id={`${uid}-role-${option}-description`} class="text-secondary text-sm">
                    {spaceRoleDescription(option)}
                  </p>
                </div>
              </div>
            {/each}
          </RadioGroup.Root>
          {#if groupNote}
            <p id={`${uid}-group-note`} class="text-sm">{groupNote}</p>
          {/if}
        </Field.Set>

        <ReasonField
          id={`${uid}-reason`}
          label={m.admin_spaces_join_reason_label()}
          help={m.admin_spaces_join_reason_help()}
          bind:value={reason}
          bind:ref={reasonInput}
          error={reasonMessage}
        >
          {#snippet helpLink()}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- external docs site -->
            <a
              href={docsUrl("guides/space-oversight", getLocale(), "join-a-space")}
              target="_blank"
              rel="noreferrer"
              class="inline-flex items-center gap-1"
            >
              {m.read_more()}
              <ExternalLink class="size-3.5" aria-hidden="true" />
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/snippet}
        </ReasonField>

        {#if serverError}
          <div
            bind:this={errorAlert}
            role="alert"
            class="bg-negative-dimmer text-negative-stronger flex items-start gap-2 rounded-lg p-3 text-sm"
          >
            <CircleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p class="min-w-0">{serverError}</p>
          </div>
        {/if}
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close
          type="button"
          class={cn(
            buttonVariants({ variant: "outline" }),
            "max-md:min-h-11",
            pending && "pointer-events-none opacity-50"
          )}
          aria-disabled={pending}
        >
          {m.cancel()}
        </Dialog.Close>
        <!-- aria-disabled, not disabled: a focused button that becomes disabled drops focus. -->
        <Button
          type="submit"
          class={["max-md:min-h-11", pending && "pointer-events-none opacity-50"]}
          aria-disabled={pending}
          aria-busy={pending}
        >
          {pending
            ? m.admin_spaces_join_pending()
            : m.admin_spaces_join_submit({ role: role ? spaceRoleLabel(role) : "" })}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
