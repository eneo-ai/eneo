<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Resolve a provider's saved outbound headers for one user in the tenant.
  Secret headers come back with their state only; the server never returns
  their value, and neither does this view try to.
-->

<script lang="ts">
  import type { OutboundHeaderPreview, UserSparse } from "@eneo/eneo-js";
  import { LoaderCircle, Search } from "@lucide/svelte";
  import { onDestroy, tick } from "svelte";

  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";

  let {
    providerId,
    hasUnsavedChanges
  }: {
    providerId: string;
    hasUnsavedChanges: boolean;
  } = $props();

  const eneo = getEneo();
  const uid = $props.id();

  const MIN_QUERY = 2;

  let pickerOpen = $state(false);
  let pickerTrigger = $state<HTMLButtonElement | null>(null);
  let query = $state("");
  let results = $state<UserSparse[]>([]);
  let searchState = $state<"idle" | "loading" | "done" | "error">("idle");
  let selected = $state<UserSparse | null>(null);
  let preview = $state<OutboundHeaderPreview | null>(null);
  let loading = $state(false);
  let announcement = $state("");

  // Only the latest search and preview may land: an older response arriving
  // late must not overwrite a newer one, or appear after the view is gone.
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  let searchRequest = 0;
  let previewRequest = 0;

  onDestroy(() => {
    clearTimeout(searchTimer);
    searchRequest += 1;
    previewRequest += 1;
  });

  function setQuery(value: string) {
    query = value;
    clearTimeout(searchTimer);
    searchRequest += 1;
    const current = value.trim();
    if (current.length < MIN_QUERY) {
      results = [];
      searchState = "idle";
      return;
    }
    searchState = "loading";
    const request = searchRequest;
    searchTimer = setTimeout(() => void search(current, request), 250);
  }

  async function search(current: string, request: number) {
    try {
      const response = await eneo.users.list({
        includeDetails: true,
        search_email: current,
        page: 1,
        page_size: 8
      });
      if (request !== searchRequest) return;
      results = response?.items ?? [];
      searchState = "done";
    } catch {
      if (request !== searchRequest) return;
      results = [];
      searchState = "error";
    }
  }

  function select(user: UserSparse) {
    selected = user;
    preview = null;
    announcement = "";
    previewRequest += 1;
    loading = false;
    pickerOpen = false;
    void tick().then(() => pickerTrigger?.focus());
  }

  async function runPreview() {
    if (!selected) return;
    previewRequest += 1;
    const request = previewRequest;
    loading = true;
    try {
      const result = await eneo.modelProviders.previewOutboundHeaders(
        { id: providerId },
        { userId: selected.id }
      );
      if (request !== previewRequest) return;
      preview = result;
      announcement = result.blocked
        ? m.outbound_headers_preview_blocked()
        : m.outbound_headers_preview_sent();
    } catch (e: unknown) {
      if (request !== previewRequest) return;
      toastError(e, m.outbound_headers_preview_title());
    } finally {
      if (request === previewRequest) loading = false;
    }
  }

  function stateLabel(state: OutboundHeaderPreview["headers"][number]["state"]): string {
    if (state === "resolved") return m.outbound_headers_preview_state_resolved();
    if (state === "missing") return m.outbound_headers_preview_state_missing();
    return m.outbound_headers_preview_state_invalid();
  }

  function reasonLabel(reason: string | null | undefined): string | null {
    if (reason === "control_character") return m.outbound_headers_reason_control_character();
    if (reason === "non_ascii") return m.outbound_headers_reason_non_ascii();
    if (reason === "value_too_long") return m.outbound_headers_reason_value_too_long();
    return null;
  }

  // Only reasons no single header row explains.
  function blockedReasonLabel(reason: string | null | undefined): string | null {
    if (reason === "total_size_exceeded") return m.outbound_headers_reason_total_size();
    return null;
  }

  function policyLabel(policy: string | null | undefined): string | null {
    if (policy === "omit") return m.outbound_headers_on_missing_omit();
    if (policy === "fallback") return m.outbound_headers_on_missing_fallback();
    if (policy === "fail") return m.outbound_headers_on_missing_fail();
    return null;
  }
</script>

<Field.Set class="border-border border-t pt-4">
  <Field.Legend>{m.outbound_headers_preview_title()}</Field.Legend>
  <Field.Description>{m.outbound_headers_preview_description()}</Field.Description>

  {#if hasUnsavedChanges}
    <p class="text-muted-foreground text-sm">{m.outbound_headers_preview_unsaved()}</p>
  {:else}
    <div class="flex items-end gap-2">
      <Field.Field class="min-w-0 flex-1">
        <Field.Label id="{uid}-user-label" for="{uid}-user">
          {m.outbound_headers_preview_user()}
        </Field.Label>
        <Popover.Root bind:open={pickerOpen}>
          <Popover.Trigger>
            {#snippet child({ props })}
              <button
                {...props}
                bind:this={pickerTrigger}
                id="{uid}-user"
                aria-labelledby="{uid}-user-label {uid}-user"
                type="button"
                class={buttonVariants({
                  variant: "outline",
                  class: "w-full justify-between font-normal"
                })}
              >
                <span class="truncate" class:text-muted-foreground={!selected}>
                  {selected?.email ?? m.outbound_headers_preview_choose_user()}
                </span>
                <Search aria-hidden="true" />
              </button>
            {/snippet}
          </Popover.Trigger>
          <Popover.Content align="start" class="w-(--bits-popover-anchor-width) p-0">
            <Command.Root shouldFilter={false} label={m.outbound_headers_preview_search()}>
              <Command.Input
                value={query}
                oninput={(event) => setQuery(event.currentTarget.value)}
                placeholder={m.outbound_headers_preview_search()}
                aria-label={m.outbound_headers_preview_search()}
              />
              <Command.List aria-busy={searchState === "loading"}>
                {#if searchState === "error"}
                  <div class="flex flex-col items-center gap-2 px-4 py-6 text-center">
                    <p class="text-destructive text-sm" role="alert">
                      {m.outbound_headers_preview_search_failed()}
                    </p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onclick={() => setQuery(query)}
                    >
                      {m.retry()}
                    </Button>
                  </div>
                {:else if searchState === "loading"}
                  <p class="text-muted-foreground px-4 py-6 text-center text-sm" role="status">
                    {m.loading()}
                  </p>
                {:else if searchState === "idle"}
                  <p class="text-muted-foreground px-4 py-6 text-center text-sm">
                    {m.outbound_headers_preview_search_hint()}
                  </p>
                {:else}
                  {#each results as user (user.id)}
                    <Command.Item value={user.id} onSelect={() => select(user)}>
                      {user.email}
                    </Command.Item>
                  {:else}
                    <p class="text-muted-foreground px-4 py-6 text-center text-sm" role="status">
                      {m.outbound_headers_preview_no_users()}
                    </p>
                  {/each}
                {/if}
              </Command.List>
            </Command.Root>
          </Popover.Content>
        </Popover.Root>
      </Field.Field>
      <Button type="button" variant="outline" disabled={!selected || loading} onclick={runPreview}>
        {#if loading}<LoaderCircle class="animate-spin" aria-hidden="true" />{/if}
        {m.outbound_headers_preview_run()}
      </Button>
    </div>

    {#if preview}
      {@const blockedReason = blockedReasonLabel(preview.blocked_reason)}
      <div class="flex flex-col gap-2">
        <p class={preview.blocked ? "text-destructive text-sm" : "text-sm"}>
          {preview.blocked
            ? m.outbound_headers_preview_blocked()
            : m.outbound_headers_preview_sent()}
        </p>
        {#if preview.destination_problem}
          <p class="text-destructive text-sm">{m.outbound_headers_destination_problem()}</p>
        {/if}
        {#if blockedReason}
          <p class="text-destructive text-sm">{blockedReason}</p>
        {/if}
        <ul class="border-border flex flex-col divide-y rounded-lg border">
          {#each preview.headers as header (header.name)}
            {@const reason = reasonLabel(header.reason)}
            {@const policy = policyLabel(header.policy)}
            <li class="flex flex-col gap-0.5 px-3 py-2 text-sm">
              <span class="flex justify-between gap-2">
                <span class="flex items-center gap-2">
                  <span class="font-mono">{header.name}</span>
                  {#if header.secret}
                    <Badge variant="outline">{m.outbound_headers_secret()}</Badge>
                  {/if}
                </span>
                <span class={header.state === "invalid" ? "text-destructive" : ""}>
                  {stateLabel(header.state)}{#if policy}&nbsp;· {policy}{/if}
                </span>
              </span>
              {#if header.secret}
                <span class="text-muted-foreground text-xs">
                  {m.outbound_headers_preview_secret_hidden()}
                </span>
              {:else if header.value}
                <span class="text-muted-foreground font-mono text-xs break-all">
                  {header.value}
                </span>
              {/if}
              {#if reason}
                <span class="text-destructive text-xs">{reason}</span>
              {/if}
              {#if header.missing_dynamic_values && header.missing_dynamic_values.length > 0}
                <span class="text-muted-foreground text-xs">
                  {m.outbound_headers_preview_missing_values({
                    tokens: header.missing_dynamic_values.join(", ")
                  })}
                </span>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}

  <p class="sr-only" aria-live="polite" aria-atomic="true">{announcement}</p>
</Field.Set>
