<script lang="ts">
  import { slide } from "svelte/transition";
  import { Clock, AlertTriangle, X, BellOff, Bell } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import type { ExpiringKeyDisplayItem, ExpiryLevel } from "./expirationUtils";
  import { isDismissed, dismiss, isMutedNonCritical, setMutedNonCritical } from "./expirationPrefs";

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
    return items.filter((item) => {
      // Urgent and expired are always visible
      if (item.level === "urgent" || item.level === "expired") return true;
      // Muted non-critical hides notice + warning
      if (muted) return false;
      return true;
    }).filter((item) => {
      // Check persistent dismiss (warning only, urgent/expired never dismissible)
      if (item.level !== "warning") return true;
      const key = items.find(i => i.id === item.id);
      if (!key) return true;
      return !isDismissed(ctx, item.id, "", item.level) && !dismissed.has(`${item.id}:${item.level}`);
    });
  });

  // Counts by severity
  const expiredCount = $derived(visibleItems.filter(i => i.level === "expired").length);
  const urgentCount = $derived(visibleItems.filter(i => i.level === "urgent").length);
  const warningCount = $derived(visibleItems.filter(i => i.level === "warning").length);

  // Earliest expiry across all visible
  const earliestDays = $derived.by(() => {
    if (visibleItems.length === 0) return null;
    return Math.min(...visibleItems.map(i => i.daysRemaining));
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

  function formatCount(count: number, oneKey: () => string, manyKeys: (p: { count: number }) => string): string {
    return count === 1 ? oneKey() : manyKeys({ count });
  }

  function buildMessage(): string {
    const parts: string[] = [];
    if (expiredCount > 0) {
      parts.push(formatCount(expiredCount, m.api_keys_expiring_expired_one, m.api_keys_expiring_expired_many));
    }
    if (urgentCount > 0) {
      parts.push(formatCount(urgentCount, m.api_keys_expiring_urgent_one, m.api_keys_expiring_urgent_many));
    }
    if (warningCount > 0) {
      parts.push(formatCount(warningCount, m.api_keys_expiring_warning_one, m.api_keys_expiring_warning_many));
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
    class="rounded-xl border {compact ? 'px-4 py-3' : 'px-5 py-4'} {isUrgent
      ? 'border-negative/30 bg-negative/5 dark:bg-negative/8'
      : 'border-caution/30 bg-caution/5 dark:bg-caution/8'}"
  >
    <div class="flex items-start gap-3 {compact ? 'items-center' : ''}">
      <!-- Icon -->
      <div class="flex-shrink-0 mt-0.5 {compact ? 'mt-0' : ''}">
        {#if isUrgent}
          <AlertTriangle class="h-4 w-4 text-negative" />
        {:else}
          <Clock class="h-4 w-4 text-caution" />
        {/if}
      </div>

      <!-- Content -->
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium {isUrgent ? 'text-negative' : 'text-caution'}">
          {buildMessage()}
        </p>
        {#if !compact && earliestDays !== null}
          <p class="text-xs mt-1 {isUrgent ? 'text-negative/70' : 'text-caution/70'}">
            {formatEarliestExpiry()}
            {#if visibleItems.some(i => i.suspended)}
              <span class="opacity-70"> &middot; {m.api_keys_expiring_includes_suspended()}</span>
            {/if}
          </p>
        {/if}
      </div>

      <!-- Actions -->
      <div class="flex items-center gap-2 flex-shrink-0">
        {#if !isUrgent && visibleItems.some(i => i.level === "warning")}
          <button
            type="button"
            onclick={handleDismissWarnings}
            class="p-1 rounded-md transition-colors hover:bg-caution/10 text-caution/60 hover:text-caution"
            title={m.api_keys_expiring_dismiss()}
          >
            <X class="h-3.5 w-3.5" />
          </button>
        {/if}
        <button
          type="button"
          onclick={handleToggleMute}
          class="p-1 rounded-md transition-colors {isUrgent
            ? 'hover:bg-negative/10 text-negative/50 hover:text-negative'
            : 'hover:bg-caution/10 text-caution/50 hover:text-caution'}"
          title={muted ? m.api_keys_expiring_unmute() : m.api_keys_expiring_mute()}
        >
          {#if muted}
            <Bell class="h-3.5 w-3.5" />
          {:else}
            <BellOff class="h-3.5 w-3.5" />
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}
