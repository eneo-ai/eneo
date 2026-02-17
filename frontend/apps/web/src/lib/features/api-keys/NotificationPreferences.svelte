<script lang="ts">
  import { onMount } from "svelte";
  import { getIntric } from "$lib/core/Intric";
  import { getExpiringKeysStore } from "$lib/features/api-keys/expiringKeysStore";
  import { Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import {
    extractFollowedKeyIds,
    getAdminNotificationPolicy,
    getNotificationPreferences,
    listNotificationSubscriptions,
    updateNotificationPreferences
  } from "$lib/features/api-keys/notificationPreferences";
  import { summaryToDisplayItems } from "$lib/features/api-keys/expirationUtils";
  import type { ExpiringKeyDisplayItem } from "$lib/features/api-keys/expirationUtils";
  import { Bell, BellOff, ShieldAlert } from "lucide-svelte";
  import { slide } from "svelte/transition";

  let {
    onExpiringItemsChanged,
    onError,
    onFollowedKeysChanged,
    onNotificationsEnabledChanged
  } = $props<{
    onExpiringItemsChanged: (items: ExpiringKeyDisplayItem[]) => void;
    onError: (msg: string) => void;
    onFollowedKeysChanged: (ids: Set<string>, hasSubscriptions: boolean) => void;
    onNotificationsEnabledChanged: (enabled: boolean) => void;
  }>();

  const intric = getIntric();
  const { forceRefresh: forceRefreshExpiringStore } = getExpiringKeysStore();

  // Notification state
  let notificationsEnabled = $state(false);
  let notificationDaysInput = $state("");
  let autoFollowPublishedAssistants = $state(false);
  let autoFollowPublishedApps = $state(false);
  let notificationSettingsLoading = $state(true);
  let notificationSettingsSaving = $state(false);
  let showCustomInput = $state(false);

  // Policy state
  let notificationPolicyEnabled = $state<boolean | null>(null);
  let notificationPolicyMaxDays = $state<number | null>(null);
  let allowAutoFollowAssistants = $state<boolean | null>(null);
  let allowAutoFollowApps = $state<boolean | null>(null);

  // Derived
  const reminderDayDefaults = [1, 3, 7, 14, 30];
  const selectedReminderDays = $derived.by(() => parseDayValues(notificationDaysInput));
  const reminderDayOptions = $derived.by(() => {
    const combined = Array.from(new Set([...reminderDayDefaults, ...selectedReminderDays]));
    const limited =
      notificationPolicyMaxDays != null && notificationPolicyMaxDays > 0
        ? combined.filter((day) => day <= notificationPolicyMaxDays!)
        : combined;
    return limited.sort((a, b) => a - b);
  });

  const isPolicyBlocked = $derived(notificationPolicyEnabled === false);

  function parseDayValues(value: string): number[] {
    return Array.from(
      new Set(
        value
          .split(/[,\s]+/)
          .map((item) => Number(item))
          .filter((item) => Number.isFinite(item) && item > 0)
          .map((item) => Math.floor(item))
      )
    ).sort((a, b) => b - a);
  }

  async function loadExpiring({
    enabled = notificationsEnabled,
    hasSubscriptions,
    days = notificationDaysInput
  }: {
    enabled?: boolean;
    hasSubscriptions: boolean;
    days?: string;
  }) {
    if (!enabled || !hasSubscriptions) {
      onExpiringItemsChanged([]);
      return;
    }
    const parsedDays = parseDayValues(days);
    const windowDays = parsedDays.length > 0 ? Math.max(...parsedDays) : 30;
    try {
      const summary = await intric.apiKeys.expiringSoon({
        days: windowDays,
        mode: "subscribed"
      });
      onExpiringItemsChanged(summaryToDisplayItems(summary.items));
    } catch {
      // Non-critical — silent fail
    }
  }

  async function loadNotificationSettings() {
    notificationSettingsLoading = true;
    try {
      const [preferences, subscriptions, policy] = await Promise.all([
        getNotificationPreferences(intric),
        listNotificationSubscriptions(intric),
        getAdminNotificationPolicy(intric).catch(() => null)
      ]);
      notificationsEnabled = preferences.enabled;
      notificationDaysInput = preferences.days_before_expiry.join(", ");
      autoFollowPublishedAssistants = preferences.auto_follow_published_assistants;
      autoFollowPublishedApps = preferences.auto_follow_published_apps;
      notificationPolicyEnabled = policy?.enabled ?? null;
      notificationPolicyMaxDays = policy?.max_days_before_expiry ?? null;
      allowAutoFollowAssistants = policy?.allow_auto_follow_published_assistants ?? null;
      allowAutoFollowApps = policy?.allow_auto_follow_published_apps ?? null;
      const followedKeyIds = extractFollowedKeyIds(subscriptions);
      const hasSubscriptions = subscriptions.length > 0;
      onFollowedKeysChanged(followedKeyIds, hasSubscriptions);
      onNotificationsEnabledChanged(preferences.enabled);
      await loadExpiring({
        enabled: preferences.enabled,
        hasSubscriptions,
        days: preferences.days_before_expiry.join(", ")
      });
    } catch (error) {
      console.error(error);
    } finally {
      notificationSettingsLoading = false;
    }
  }

  async function handleNotificationsToggle({
    current,
    next
  }: {
    current: boolean;
    next: boolean;
  }) {
    const previous = current;
    notificationsEnabled = next;
    onNotificationsEnabledChanged(next);
    notificationSettingsSaving = true;
    try {
      const updated = await updateNotificationPreferences(intric, { enabled: next });
      notificationsEnabled = updated.enabled;
      notificationDaysInput = updated.days_before_expiry.join(", ");
      autoFollowPublishedAssistants = updated.auto_follow_published_assistants;
      autoFollowPublishedApps = updated.auto_follow_published_apps;
      onNotificationsEnabledChanged(updated.enabled);
      if (next && !updated.enabled) {
        notificationPolicyEnabled = false;
        onError(m.api_keys_notifications_policy_disabled_error());
      }
      await forceRefreshExpiringStore();
    } catch (error: any) {
      console.error(error);
      notificationsEnabled = previous;
      onNotificationsEnabledChanged(previous);
      onError(error?.getReadableMessage?.() ?? m.something_went_wrong());
    } finally {
      notificationSettingsSaving = false;
    }
  }

  let saveTimer: ReturnType<typeof setTimeout> | undefined;

  function debouncedSaveDays() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => void saveNotificationDays(), 400);
  }

  function toggleReminderDay(day: number) {
    if (notificationSettingsSaving) return;
    const next = new Set(selectedReminderDays);
    if (next.has(day)) {
      next.delete(day);
    } else {
      next.add(day);
    }
    if (next.size === 0) {
      next.add(day);
    }
    notificationDaysInput = Array.from(next)
      .sort((a, b) => b - a)
      .join(", ");
    debouncedSaveDays();
  }

  async function saveNotificationDays() {
    const parsed = parseDayValues(notificationDaysInput);
    if (parsed.length === 0) {
      onError(m.api_keys_notifications_days_validation());
      return;
    }
    notificationSettingsSaving = true;
    try {
      const updated = await updateNotificationPreferences(intric, {
        days_before_expiry: parsed
      });
      notificationsEnabled = updated.enabled;
      notificationDaysInput = updated.days_before_expiry.join(", ");
      autoFollowPublishedAssistants = updated.auto_follow_published_assistants;
      autoFollowPublishedApps = updated.auto_follow_published_apps;
      if (!updated.enabled) {
        notificationPolicyEnabled = false;
      }
      await forceRefreshExpiringStore();
    } catch (error: any) {
      console.error(error);
      onError(error?.getReadableMessage?.() ?? m.something_went_wrong());
    } finally {
      notificationSettingsSaving = false;
    }
  }

  async function handleAutoFollowAssistantsToggle({
    current,
    next
  }: {
    current: boolean;
    next: boolean;
  }) {
    autoFollowPublishedAssistants = next;
    notificationSettingsSaving = true;
    try {
      const updated = await updateNotificationPreferences(intric, {
        auto_follow_published_assistants: next
      });
      notificationsEnabled = updated.enabled;
      notificationDaysInput = updated.days_before_expiry.join(", ");
      autoFollowPublishedAssistants = updated.auto_follow_published_assistants;
      autoFollowPublishedApps = updated.auto_follow_published_apps;
      if (next && !updated.auto_follow_published_assistants) {
        allowAutoFollowAssistants = false;
        onError(m.api_keys_notifications_auto_follow_assistants_policy_error());
      }
    } catch (error: any) {
      console.error(error);
      autoFollowPublishedAssistants = current;
      onError(error?.getReadableMessage?.() ?? m.something_went_wrong());
    } finally {
      notificationSettingsSaving = false;
    }
  }

  async function handleAutoFollowAppsToggle({
    current,
    next
  }: {
    current: boolean;
    next: boolean;
  }) {
    autoFollowPublishedApps = next;
    notificationSettingsSaving = true;
    try {
      const updated = await updateNotificationPreferences(intric, {
        auto_follow_published_apps: next
      });
      notificationsEnabled = updated.enabled;
      notificationDaysInput = updated.days_before_expiry.join(", ");
      autoFollowPublishedAssistants = updated.auto_follow_published_assistants;
      autoFollowPublishedApps = updated.auto_follow_published_apps;
      if (next && !updated.auto_follow_published_apps) {
        allowAutoFollowApps = false;
        onError(m.api_keys_notifications_auto_follow_apps_policy_error());
      }
    } catch (error: any) {
      console.error(error);
      autoFollowPublishedApps = current;
      onError(error?.getReadableMessage?.() ?? m.something_went_wrong());
    } finally {
      notificationSettingsSaving = false;
    }
  }

  // Expose a method for parent to trigger follow-change refresh
  export async function refreshSubscriptions() {
    try {
      const subscriptions = await listNotificationSubscriptions(intric);
      const followedKeyIds = extractFollowedKeyIds(subscriptions);
      const hasSubscriptions = subscriptions.length > 0;
      onFollowedKeysChanged(followedKeyIds, hasSubscriptions);
      await loadExpiring({
        enabled: notificationsEnabled,
        hasSubscriptions
      });
      await forceRefreshExpiringStore();
    } catch (error) {
      console.error(error);
    }
  }

  onMount(() => {
    void loadNotificationSettings();
  });
</script>

<div class="rounded-xl border border-default bg-primary shadow-sm overflow-hidden">
  <!-- Header -->
  <div class="flex items-center justify-between gap-4 px-5 py-3.5">
    <div class="flex items-center gap-3 min-w-0">
      <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-default/10">
        {#if notificationsEnabled && !isPolicyBlocked}
          <Bell class="h-4 w-4 text-accent-default" />
        {:else}
          <BellOff class="h-4 w-4 text-muted" />
        {/if}
      </div>
      <h3 class="text-sm font-semibold text-primary">
        {m.api_keys_notifications_settings_title()}
      </h3>
    </div>
    <div class="shrink-0">
      <Input.Switch
        bind:value={notificationsEnabled}
        sideEffect={handleNotificationsToggle}
        disabled={notificationSettingsLoading || notificationSettingsSaving || isPolicyBlocked}
      />
    </div>
  </div>

  <!-- Policy-blocked banner -->
  {#if isPolicyBlocked}
    <div class="mx-5 mb-4 flex items-center gap-3 rounded-lg border border-negative-default/20 bg-negative-dimmer/50 px-4 py-3">
      <ShieldAlert class="h-4 w-4 text-negative-default shrink-0" />
      <p class="text-xs text-negative-default">
        {m.api_keys_notifications_policy_header_hint()}
      </p>
    </div>
  {/if}

  <!-- Disabled hint -->
  {#if !notificationsEnabled && !isPolicyBlocked && !notificationSettingsLoading}
    <p class="px-5 pb-4 text-xs text-muted">
      {m.api_keys_notifications_enable_to_edit_hint()}
    </p>
  {/if}

  <!-- Expanded body (only when enabled) -->
  {#if notificationsEnabled && !isPolicyBlocked}
    <div class="border-t border-default px-5 py-4 space-y-4" transition:slide={{ duration: 200 }}>
      <p class="text-xs text-secondary">
        {m.api_keys_notifications_settings_description()}
      </p>

      <!-- Reminder schedule -->
      <div class="space-y-3" class:opacity-50={notificationSettingsSaving} class:pointer-events-none={notificationSettingsSaving}>
        <!-- Quick day chips -->
        <div class="flex flex-wrap gap-1.5">
          {#each reminderDayOptions as day (day)}
            {@const isSelected = selectedReminderDays.includes(day)}
            <button
              type="button"
              style="font-variant-numeric: tabular-nums"
              class="inline-flex h-8 min-w-[42px] items-center justify-center rounded-lg px-3 text-xs font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-default/50 {isSelected
                ? 'bg-accent-default text-on-fill shadow-sm'
                : 'border border-default bg-primary text-secondary hover:text-primary hover:border-stronger'}"
              aria-pressed={isSelected}
              aria-label={m.api_keys_notifications_day_chip_aria_label({ day })}
              disabled={notificationSettingsSaving}
              onclick={() => toggleReminderDay(day)}
            >
              {day}d
            </button>
          {/each}
        </div>

        <!-- Custom days disclosure -->
        {#if showCustomInput}
          <div class="max-w-[280px]" transition:slide={{ duration: 150 }}>
            <Input.Text
              bind:value={notificationDaysInput}
              label={m.api_keys_notifications_days_label()}
              placeholder="30, 14, 7, 3, 1"
              disabled={notificationSettingsSaving}
              on:blur={debouncedSaveDays}
            />
          </div>
        {:else}
          <button
            type="button"
            class="text-xs text-accent-default hover:underline"
            onclick={() => (showCustomInput = true)}
          >
            {m.api_keys_notifications_customize_days()}
          </button>
        {/if}

        <p class="text-xs text-muted leading-relaxed">
          {m.api_keys_notifications_days_help()}
          {#if notificationPolicyMaxDays}
            {m.api_keys_notifications_max_days_hint({ days: notificationPolicyMaxDays })}
          {/if}
        </p>
      </div>

      <!-- Auto-follow settings -->
      <div class="space-y-3 border-t border-default pt-4" class:opacity-50={notificationSettingsSaving} class:pointer-events-none={notificationSettingsSaving}>
        <!-- Assistants -->
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <p class="text-sm font-medium text-primary">
              {m.api_keys_notifications_auto_follow_assistants_title()}
            </p>
            <p class="mt-0.5 text-xs text-secondary">
              {m.api_keys_notifications_auto_follow_assistants_description()}
            </p>
            {#if allowAutoFollowAssistants === false}
              <p class="mt-1 text-xs text-negative-default">
                {m.api_keys_notifications_auto_follow_assistants_locked_hint()}
              </p>
            {/if}
          </div>
          <div class="shrink-0 pt-0.5">
            <Input.Switch
              bind:value={autoFollowPublishedAssistants}
              sideEffect={handleAutoFollowAssistantsToggle}
              disabled={notificationSettingsSaving || allowAutoFollowAssistants === false}
            />
          </div>
        </div>

        <!-- Apps -->
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <p class="text-sm font-medium text-primary">
              {m.api_keys_notifications_auto_follow_apps_title()}
            </p>
            <p class="mt-0.5 text-xs text-secondary">
              {m.api_keys_notifications_auto_follow_apps_description()}
            </p>
            {#if allowAutoFollowApps === false}
              <p class="mt-1 text-xs text-negative-default">
                {m.api_keys_notifications_auto_follow_apps_locked_hint()}
              </p>
            {/if}
          </div>
          <div class="shrink-0 pt-0.5">
            <Input.Switch
              bind:value={autoFollowPublishedApps}
              sideEffect={handleAutoFollowAppsToggle}
              disabled={notificationSettingsSaving || allowAutoFollowApps === false}
            />
          </div>
        </div>
      </div>
    </div>
  {/if}

  <!-- SR-only live region -->
  <div class="sr-only" aria-live="polite">
    {notificationsEnabled
      ? m.api_keys_notifications_aria_enabled()
      : m.api_keys_notifications_aria_disabled()}
  </div>
</div>
