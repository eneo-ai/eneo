<script lang="ts">
  import { slide } from "svelte/transition";
  import { Clock, AlertTriangle, X, BellOff, Bell } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import type { ExpiringKeyDisplayItem, ExpiryLevel } from "./expirationUtils";
  import { isDismissed, dismiss, isMutedNonCritical, setMutedNonCritical } from "./expirationPrefs";
  import { Button } from "$lib/components/ui/button/index.js";

  let {
    items,
    tenantId,
    userId,
    compact = false,
    qualifier = ""
  }: {
    items: ExpiringKeyDisplayItem[];
    tenantId: string;
    userId: string;
    compact?: boolean;
    qualifier?: string;
  } = $props();

  let dismissed = $state<Set<string>>(new Set());
  let muteOverride = $state<boolean | null>(null);

  const ctx = $derived({ tenantId, userId });
  const muted = $derived(muteOverride ?? isMutedNonCritical(ctx));

  // Highest severity across all visible items
  const highestSeverity = $derived.by((): ExpiryLevel => {
    for (const item of visibleItems) {
      if (item.level === "expired") return "expired";
      if (item.level === "urgent") return "urgent";
      if (item.level === "warning") return "warning";
    }
    return "notice";
  });

  // Items filtered by dismiss state, mute preference, and local dismissals
  const visibleItems = $derived.by(() => {
    return items
      .filter((item) => {
        // Urgent and expired are always visible
        if (item.level === "urgent" || item.level === "expired") return true;
        // Muted non-critical hides notice + warning
        if (muted) return false;
        return true;
      })
      .filter((item) => {
        // Check persistent dismiss (warning only, urgent/expired never dismissible)
        if (item.level !== "warning") return true;
        const key = items.find((i) => i.id === item.id);
        if (!key) return true;
        return (
          !isDismissed(ctx, item.id, "", item.level) && !dismissed.has(`${item.id}:${item.level}`)
        );
      });
  });

  // Counts by severity
  const expiredCount = $derived(visibleItems.filter((i) => i.level === "expired").length);
  const urgentCount = $derived(visibleItems.filter((i) => i.level === "urgent").length);
  const warningCount = $derived(visibleItems.filter((i) => i.level === "warning").length);

  // Earliest expiry across all visible
  const earliestDays = $derived.by(() => {
    if (visibleItems.length === 0) return null;
    return Math.min(...visibleItems.map((i) => i.daysRemaining));
  });

  // Should we show the banner at all?
  const showBanner = $derived(visibleItems.length > 0);

  // Is it an urgent/expired-level banner?
  const isUrgent = $derived(highestSeverity === "urgent" || highestSeverity === "expired");

  function handleDismissWarnings() {
    for (const item of visibleItems) {
      if (item.level === "warning") {
        dismiss(ctx, item.id, "", item.level);
        dismissed = new Set([...dismissed, `${item.id}:${item.level}`]);
      }
    }
  }

  function handleToggleMute() {
    const newValue = !muted;
    muteOverride = newValue;
    setMutedNonCritical(ctx, newValue);
  }

  function formatCount(
    count: number,
    oneKey: () => string,
    manyKeys: (p: { count: number }) => string
  ): string {
    return count === 1 ? oneKey() : manyKeys({ count });
  }

  function buildMessage(): string {
    const parts: string[] = [];
    if (expiredCount > 0) {
      parts.push(
        formatCount(expiredCount, m.api_keys_expiring_expired_one, m.api_keys_expiring_expired_many)
      );
    }
    if (urgentCount > 0) {
      parts.push(
        formatCount(urgentCount, m.api_keys_expiring_urgent_one, m.api_keys_expiring_urgent_many)
      );
    }
    if (warningCount > 0) {
      parts.push(
        formatCount(warningCount, m.api_keys_expiring_warning_one, m.api_keys_expiring_warning_many)
      );
    }
    let msg = parts.join(", ");
    if (qualifier) {
      msg += ` ${qualifier}`;
    }
    return msg;
  }

  function formatEarliestExpiry(): string {
    if (earliestDays === null) return "";
    if (earliestDays < 0) return m.api_keys_expiring_already_expired();
    if (earliestDays === 0) return m.api_keys_expiring_earliest_today();
    if (earliestDays === 1) return m.api_keys_expiring_earliest_tomorrow();
    return m.api_keys_expiring_earliest_days({ days: earliestDays });
  }
</script>

{#if showBanner}
  <div
    transition:slide={{ duration: 200 }}
    role={isUrgent ? "alert" : "status"}
    aria-live={isUrgent ? "assertive" : "polite"}
    class="rounded-xl border {compact ? 'px-4 py-3' : 'px-5 py-4'} {isUrgent
      ? 'border-negative-default/30 bg-negative-default/5 dark:bg-negative-default/8'
      : 'border-caution/30 bg-caution/5 dark:bg-caution/8'}"
  >
    <div class="flex items-start gap-3 {compact ? 'items-center' : ''}">
      <!-- Icon -->
      <div class="mt-0.5 flex-shrink-0 {compact ? 'mt-0' : ''}" aria-hidden="true">
        {#if isUrgent}
          <AlertTriangle class="text-negative-stronger h-4 w-4" />
        {:else}
          <Clock class="text-caution h-4 w-4" />
        {/if}
      </div>

      <!-- Content -->
      <div class="min-w-0 flex-1">
        <p class="text-sm font-medium {isUrgent ? 'text-negative-stronger' : 'text-caution'}">
          {buildMessage()}
        </p>
        {#if !compact && earliestDays !== null}
          <p class="mt-1 text-xs {isUrgent ? 'text-negative-stronger/70' : 'text-caution/70'}">
            {formatEarliestExpiry()}
            {#if visibleItems.some((i) => i.suspended)}
              <span class="opacity-70"> &middot; {m.api_keys_expiring_includes_suspended()}</span>
            {/if}
          </p>
        {/if}
      </div>

      <!-- Actions -->
      <div class="flex flex-shrink-0 items-center gap-2">
        {#if !isUrgent && visibleItems.some((i) => i.level === "warning")}
          <Button
            variant="ghost"
            size="icon-sm"
            onclick={handleDismissWarnings}
            aria-label={m.api_keys_expiring_dismiss()}
            class="text-caution/70 hover:bg-caution/10 hover:text-caution"
          >
            <X />
          </Button>
        {/if}
        <Button
          variant="ghost"
          size="icon-sm"
          onclick={handleToggleMute}
          aria-label={muted ? m.api_keys_expiring_unmute() : m.api_keys_expiring_mute()}
          class={isUrgent
            ? "text-negative-stronger/60 hover:bg-negative-default/10 hover:text-negative-stronger"
            : "text-caution/60 hover:bg-caution/10 hover:text-caution"}
        >
          {#if muted}
            <Bell />
          {:else}
            <BellOff />
          {/if}
        </Button>
      </div>
    </div>
  </div>
{/if}
