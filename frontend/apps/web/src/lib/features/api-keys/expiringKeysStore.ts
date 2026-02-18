import { browser } from "$app/environment";
import { createContext } from "$lib/core/context";
import type { Intric } from "@intric/intric-js";
import { derived, writable } from "svelte/store";
import { summaryToDisplayItems, type ExpiringKeyDisplayItem } from "./expirationUtils";
import {
  getNotificationPreferences,
  listNotificationSubscriptions
} from "./notificationPreferences";

export { getExpiringKeysStore, initExpiringKeysStore };

interface ExpiringKeysSummaryResponse {
  total_count: number;
  counts_by_severity: Record<string, number>;
  earliest_expiration: string | null;
  items: Array<{
    id: string;
    name: string;
    key_suffix: string | null;
    scope_type: string;
    scope_id: string | null;
    expires_at: string;
    suspended_at: string | null;
    severity: string;
  }>;
  truncated: boolean;
  generated_at: string;
}

const [getExpiringKeysStore, setExpiringKeysStore] =
  createContext<ReturnType<typeof createExpiringKeysStore>>("Expiring API keys notifications");

function initExpiringKeysStore(data: {
  intric: Intric;
  settings?: { api_key_expiry_notifications?: boolean };
}) {
  setExpiringKeysStore(createExpiringKeysStore(data));
}

function createExpiringKeysStore(data: {
  intric: Intric;
  settings?: { api_key_expiry_notifications?: boolean };
}) {
  const { intric } = data;
  const featureEnabled = data.settings?.api_key_expiry_notifications !== false;

  const summary = writable<ExpiringKeysSummaryResponse | null>(null);

  const displayItems = derived(summary, ($summary): ExpiringKeyDisplayItem[] => {
    if (!$summary) return [];
    return summaryToDisplayItems($summary.items);
  });

  const hasUrgent = derived(summary, ($summary) => {
    if (!$summary) return false;
    const counts = $summary.counts_by_severity;
    return (counts.urgent ?? 0) > 0 || (counts.expired ?? 0) > 0;
  });

  const hasWarning = derived(summary, ($summary) => {
    if (!$summary) return false;
    const counts = $summary.counts_by_severity;
    return (counts.warning ?? 0) > 0;
  });

  let lastFetchTime = 0;
  let inFlightPromise: Promise<void> | null = null;
  let contextLoadedAt = 0;
  let preferencesEnabled = false;
  let daysWindow = 30;
  let hasSubscriptions = false;

  const SUMMARY_TTL_MS = 60_000;
  const CONTEXT_TTL_MS = 60_000;

  async function loadNotificationContext(force = false): Promise<void> {
    if (!force && Date.now() - contextLoadedAt < CONTEXT_TTL_MS) return;

    const [preferences, subscriptions] = await Promise.all([
      getNotificationPreferences(intric),
      listNotificationSubscriptions(intric)
    ]);
    preferencesEnabled = preferences.enabled;
    daysWindow = Math.max(...preferences.days_before_expiry, 1);
    hasSubscriptions = subscriptions.length > 0;
    contextLoadedAt = Date.now();
  }

  async function refresh(): Promise<void> {
    if (!featureEnabled) {
      summary.set(null);
      return;
    }
    if (Date.now() - lastFetchTime < SUMMARY_TTL_MS) return;
    if (inFlightPromise) return inFlightPromise;

    inFlightPromise = (async () => {
      try {
        await loadNotificationContext();

        if (!preferencesEnabled || !hasSubscriptions) {
          summary.set(null);
          lastFetchTime = Date.now();
          return;
        }

        const result = await intric.apiKeys.expiringSoon({
          days: daysWindow,
          mode: "subscribed"
        });
        summary.set(result as ExpiringKeysSummaryResponse);
        lastFetchTime = Date.now();
      } catch (error) {
        console.error("ExpiringKeysStore: Could not fetch expiring keys", error);
        summary.set(null);
      } finally {
        inFlightPromise = null;
      }
    })();

    return inFlightPromise;
  }

  function forceRefresh(): Promise<void> {
    lastFetchTime = 0;
    contextLoadedAt = 0;
    return refresh();
  }

  if (browser) {
    void refresh();
  }

  return {
    state: {
      summary: { subscribe: summary.subscribe },
      displayItems: { subscribe: displayItems.subscribe },
      hasUrgent,
      hasWarning
    },
    refresh,
    forceRefresh
  };
}
