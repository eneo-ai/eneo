<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<!--
  Session-scoped advisory for users in the attached group who lack
  `shared_spaces` and will be gated by `SpaceActor` at runtime. Prefer to
  a toast because the warning must persist past 8s for admins acting on
  it. `missingCount` is authoritative; `missing` is a server-capped
  sample (see backend `INERT_SAMPLE_SIZE`) and `truncated` signals
  whether the sample omits any affected users.
-->

<script lang="ts">
  import { IconInfo } from "@intric/icons/info";
  import { IconCancel } from "@intric/icons/cancel";
  import { Button } from "@intric/ui";
  import { resolve } from "$app/paths";
  import { m } from "$lib/paraglide/messages";

  type InertMember = { id: string; email: string; username: string | null };

  type Props = {
    groupName: string;
    loginableTotal: number;
    missingCount: number;
    missing: InertMember[];
    truncated: boolean;
    // Gates the "Manage roles" remediation link — only surfaced to users
    // who actually have access to `/admin/legacy/roles`. Non-admins see
    // the help text's written instruction instead.
    canManageRoles?: boolean;
    ondismiss: () => void;
  };

  const {
    groupName,
    loginableTotal,
    missingCount,
    missing,
    truncated,
    canManageRoles = false,
    ondismiss
  }: Props = $props();

  let expanded = $state(false);

  // Stable per-instance id for aria-controls wiring on the disclosure button.
  const listId = `inert-members-${Math.random().toString(36).slice(2, 8)}`;

  const allInert = $derived(missingCount >= loginableTotal && loginableTotal > 0);
  const remaining = $derived(Math.max(missingCount - missing.length, 0));

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") ondismiss();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div
  role="status"
  class="border-warning-default bg-warning-dimmer/40 dark:bg-warning-dimmer/20 mx-4 mt-4 mb-2 rounded-lg border shadow-sm"
>
  <div class="flex items-start gap-3 p-4">
    <IconInfo class="text-warning-stronger mt-0.5 h-5 w-5 flex-shrink-0" aria-hidden="true" />

    <div class="flex min-w-0 flex-grow flex-col gap-1.5">
      <h2 class="text-warning-stronger text-sm font-medium tabular-nums">
        {#if allInert}
          {m.inert_notice_all_title({ groupName, total: loginableTotal })}
        {:else}
          {m.inert_notice_partial_title({
            count: missingCount,
            total: loginableTotal,
            groupName
          })}
        {/if}
      </h2>

      <p class="text-primary text-sm">
        {m.inert_notice_help()}
      </p>

      {#if missing.length > 0 || canManageRoles}
        <div class="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
          {#if missing.length > 0}
            <button
              type="button"
              class="text-warning-stronger hover:text-primary w-fit text-left text-sm font-medium underline-offset-2 hover:underline focus-visible:underline"
              aria-expanded={expanded}
              aria-controls={listId}
              onclick={() => (expanded = !expanded)}
            >
              {expanded ? m.inert_notice_hide_members() : m.inert_notice_show_members()}
            </button>
          {/if}

          {#if canManageRoles}
            <a
              href={resolve("/admin/legacy/roles")}
              class="text-accent-default hover:text-accent-stronger w-fit text-left text-sm font-medium underline-offset-2 hover:underline focus-visible:underline"
            >
              {m.inert_notice_manage_roles()} →
            </a>
          {/if}
        </div>
      {/if}

      {#if missing.length > 0 && expanded}
        <div
          id={listId}
          class="border-default bg-primary/60 divide-dimmer mt-1 divide-y overflow-hidden rounded-md border"
        >
          <ul class="divide-dimmer divide-y">
            {#each missing as member (member.id)}
              <li class="flex min-w-0 flex-col px-3 py-1.5">
                <span class="text-primary truncate text-sm font-medium">
                  {member.username ?? member.email}
                </span>
                {#if member.username}
                  <span class="text-secondary truncate text-xs">{member.email}</span>
                {/if}
              </li>
            {/each}
          </ul>
          {#if truncated && remaining > 0}
            <p class="text-secondary px-3 py-1.5 text-xs tabular-nums">
              {m.inert_notice_more_members({ count: remaining })}
            </p>
          {/if}
        </div>
      {/if}
    </div>

    <Button
      variant="simple"
      padding="icon"
      aria-label={m.inert_notice_dismiss()}
      class="text-secondary hover:text-primary"
      on:click={ondismiss}
    >
      <IconCancel class="h-4 w-4" />
    </Button>
  </div>
</div>
