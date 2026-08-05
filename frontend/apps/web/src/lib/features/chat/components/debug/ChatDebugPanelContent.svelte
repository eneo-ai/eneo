<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import ChevronUp from "@lucide/svelte/icons/chevron-up";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import Info from "@lucide/svelte/icons/info";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";
  import type { ChatService } from "../../ChatService.svelte";
  import type { DebugTurnOption } from "../../turnDebugProjection";
  import type { ChatDebugPanelState } from "./chatDebugPanelState.svelte";
  import SkillActivationDiagnostics from "./SkillActivationDiagnostics.svelte";
  import TurnDiagnosticsSummary from "./TurnDiagnosticsSummary.svelte";

  let {
    chat,
    state: panel,
    idPrefix
  }: { chat: ChatService; state: ChatDebugPanelState; idPrefix: string } = $props();

  const pendingDiagnosticsRefreshFailed = $derived(chat.pendingDiagnosticsRefreshFailed);
  const selectedTurnStatus = $derived(
    panel.loading
      ? m.chat_debug_loading()
      : panel.refreshing
        ? m.chat_debug_refreshing()
        : panel.loadError
          ? m.chat_debug_load_error()
          : panel.diagnostics
            ? m.chat_debug_loaded()
            : ""
  );
  const liveTurnStatus = $derived(
    panel.liveTurnPending && !pendingDiagnosticsRefreshFailed ? m.chat_debug_live_turn_title() : ""
  );

  const timeFormatter = $derived(
    new Intl.DateTimeFormat(getLocale() === "sv" ? "sv-SE" : "en-US", {
      hour: "2-digit",
      minute: "2-digit"
    })
  );
  const dateTimeFormatter = $derived(
    new Intl.DateTimeFormat(getLocale() === "sv" ? "sv-SE" : "en-US", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit"
    })
  );

  function turnLabel(turn: DebugTurnOption): string {
    const label = m.chat_debug_turn_option({ number: String(turn.turnNumber) });
    if (!turn.createdAt) return label;
    const sent = new Date(turn.createdAt);
    if (Number.isNaN(sent.getTime())) return label;
    const formatter =
      sent.toDateString() === new Date().toDateString() ? timeFormatter : dateTimeFormatter;
    return `${label} · ${formatter.format(sent)}`;
  }
</script>

<p class="sr-only" role="status" aria-live="polite" data-chat-debug-status="selected-turn">
  {selectedTurnStatus}
</p>
<p class="sr-only" role="status" aria-live="polite" data-chat-debug-status="live-turn">
  {liveTurnStatus}
</p>

<div class="border-border flex flex-col gap-2 border-b px-5 py-4">
  <label for="{idPrefix}-turn-select" class="text-xs font-medium">
    {m.chat_debug_select_turn()}
  </label>
  <div class="flex min-w-0 items-center gap-2">
    <Select.Root
      type="single"
      value={panel.selectedMessageId}
      disabled={panel.turns.length === 0}
      onValueChange={(messageId) => panel.selectTurn(messageId)}
    >
      <Select.Trigger id="{idPrefix}-turn-select" class="min-w-0 flex-1">
        <span data-slot="select-value" class="min-w-0 truncate">
          {panel.selectedTurn
            ? turnLabel(panel.selectedTurn)
            : m.chat_debug_select_turn_placeholder()}
        </span>
      </Select.Trigger>
      <Select.Content class="max-h-80 max-w-[calc(100vw-2rem)]">
        <Select.Group>
          <Select.Label>{m.chat_debug_available_turns()}</Select.Label>
          {#each panel.turns as turn (turn.messageId)}
            <Select.Item value={turn.messageId} label={turnLabel(turn)}>
              <span class="max-w-[28rem] truncate">{turnLabel(turn)}</span>
            </Select.Item>
          {/each}
        </Select.Group>
      </Select.Content>
    </Select.Root>
    <div class="flex items-center gap-1">
      <Button
        variant="outline"
        size="icon"
        disabled={panel.selectedTurnIndex <= 0}
        aria-label={m.chat_debug_previous_turn()}
        onclick={() => panel.stepTurn(-1)}
      >
        <ChevronUp aria-hidden="true" />
      </Button>
      <Button
        variant="outline"
        size="icon"
        disabled={panel.selectedTurnIndex < 0 || panel.selectedTurnIndex >= panel.turns.length - 1}
        aria-label={m.chat_debug_next_turn()}
        onclick={() => panel.stepTurn(1)}
      >
        <ChevronDown aria-hidden="true" />
      </Button>
      {#if panel.diagnostics}
        <Button
          variant="outline"
          size="icon"
          disabled={panel.refreshing}
          aria-label={m.chat_debug_refresh()}
          onclick={() => panel.retryLoad(true)}
        >
          <RotateCcw
            class={panel.refreshing ? "animate-spin motion-reduce:animate-none" : undefined}
            aria-hidden="true"
          />
        </Button>
      {/if}
    </div>
  </div>
</div>

<div class="min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-gutter:stable] @container">
  {#if panel.liveTurnPending}
    <div class="px-5 pt-5">
      <Alert.Root
        variant={pendingDiagnosticsRefreshFailed ? "destructive" : undefined}
        role={pendingDiagnosticsRefreshFailed ? "alert" : "group"}
      >
        {#if pendingDiagnosticsRefreshFailed}
          <CircleAlert aria-hidden="true" />
        {:else}
          <Info aria-hidden="true" />
        {/if}
        <Alert.Title>
          {pendingDiagnosticsRefreshFailed
            ? m.chat_debug_confirmation_error_title()
            : m.chat_debug_live_turn_title()}
        </Alert.Title>
        <Alert.Description>
          {pendingDiagnosticsRefreshFailed
            ? m.chat_debug_confirmation_error_description()
            : m.chat_debug_live_turn_description()}
        </Alert.Description>
        {#if pendingDiagnosticsRefreshFailed}
          <Alert.Action>
            <Button
              variant="outline"
              size="sm"
              onclick={() => void chat.retryPendingDiagnosticsMetadata()}
            >
              <RotateCcw data-icon="inline-start" aria-hidden="true" />
              {m.chat_debug_retry()}
            </Button>
          </Alert.Action>
        {/if}
      </Alert.Root>
    </div>
  {/if}

  {#if panel.turns.length === 0 && !panel.liveTurnPending}
    {@render EmptyState(m.chat_debug_no_turn_title(), m.chat_debug_no_turn_description())}
  {:else if panel.loading}
    <div class="flex flex-col gap-4 p-5" aria-busy="true" aria-label={m.chat_debug_loading()}>
      <Skeleton class="h-24 w-full" />
      <Skeleton class="h-32 w-full" />
      <Skeleton class="h-20 w-full" />
    </div>
  {:else if panel.loadError && !panel.diagnostics}
    <div class="p-5">
      <Alert.Root variant="destructive">
        <Alert.Title>{m.chat_debug_unavailable_title()}</Alert.Title>
        <Alert.Description>{m.chat_debug_unavailable_description()}</Alert.Description>
        <Alert.Action>
          <Button variant="outline" size="sm" onclick={() => panel.retryLoad(false)}>
            <RotateCcw data-icon="inline-start" aria-hidden="true" />
            {m.chat_debug_retry()}
          </Button>
        </Alert.Action>
      </Alert.Root>
    </div>
  {:else if panel.diagnostics && panel.turnDetails}
    {#if panel.loadError}
      <div class="px-5 pt-5">
        <Alert.Root variant="destructive">
          <Alert.Title>{m.chat_debug_refresh_error_title()}</Alert.Title>
          <Alert.Description>{m.chat_debug_refresh_error_description()}</Alert.Description>
        </Alert.Root>
      </div>
    {/if}
    <TurnDiagnosticsSummary details={panel.turnDetails} />
    {#if panel.diagnostics.skill_activation}
      <SkillActivationDiagnostics evidence={panel.diagnostics.skill_activation} />
    {:else}
      <section class="flex flex-col gap-1 px-5 py-5" aria-labelledby="{idPrefix}-legacy-skills">
        <h2 id="{idPrefix}-legacy-skills" class="text-sm font-semibold">
          {m.chat_debug_legacy_skills_title()}
        </h2>
        <p class="text-muted-foreground max-w-[65ch] text-sm leading-5">
          {m.chat_debug_legacy_skills_description()}
        </p>
      </section>
    {/if}
  {/if}
</div>

{#snippet EmptyState(title: string, description: string)}
  <div class="flex min-h-56 flex-col items-start justify-center gap-2 px-5 py-8">
    <h2 class="text-sm font-semibold">{title}</h2>
    <p class="text-muted-foreground max-w-[52ch] text-sm leading-5">{description}</p>
  </div>
{/snippet}
