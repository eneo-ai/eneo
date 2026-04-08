<script lang="ts">
  import { onMount } from "svelte";
  import { getIntric } from "$lib/core/Intric";
  import { getExpiringKeysStore } from "$lib/features/api-keys/expiringKeysStore";
  import { m } from "$lib/paraglide/messages";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
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
  import { SvelteSet } from "svelte/reactivity";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";

  let { onExpiringItemsChanged, onError, onFollowedKeysChanged, onNotificationsEnabledChanged } =
    $props<{
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

  async function handleNotificationsToggle({ current, next }: { current: boolean; next: boolean }) {
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
    } catch (error: unknown) {
      console.error(error);
      notificationsEnabled = previous;
      onNotificationsEnabledChanged(previous);
      onError(getErrorMessage(error));
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
    const next = new SvelteSet(selectedReminderDays);
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
    } catch (error: unknown) {
      console.error(error);
      onError(getErrorMessage(error));
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
    } catch (error: unknown) {
      console.error(error);
      autoFollowPublishedAssistants = current;
      onError(getErrorMessage(error));
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
    } catch (error: unknown) {
      console.error(error);
      autoFollowPublishedApps = current;
      onError(getErrorMessage(error));
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

<div class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
  <!-- Header -->
  <div class="flex items-center justify-between gap-4 px-5 py-3.5">
    <div class="flex min-w-0 items-center gap-3">
      <div
        class="bg-accent-default/10 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
      >
        {#if notificationsEnabled && !isPolicyBlocked}
          <Bell class="text-accent-default h-4 w-4" />
        {:else}
          <BellOff class="text-muted h-4 w-4" />
        {/if}
      </div>
      <h3 class="text-primary text-sm font-semibold">
        {m.api_keys_notifications_settings_title()}
      </h3>
    </div>
    <div class="shrink-0">
      <Switch
        checked={notificationsEnabled}
        onCheckedChange={(next) =>
          handleNotificationsToggle({ current: notificationsEnabled, next })}
        disabled={notificationSettingsLoading || notificationSettingsSaving || isPolicyBlocked}
        aria-label={m.api_keys_notifications_settings_title()}
      />
    </div>
  </div>

  <!-- Policy-blocked banner -->
  {#if isPolicyBlocked}
    <Alert.Root variant="destructive" class="mx-5 mb-4">
      <ShieldAlert />
      <Alert.Description>
        {m.api_keys_notifications_policy_header_hint()}
      </Alert.Description>
    </Alert.Root>
  {/if}

  <!-- Disabled hint -->
  {#if !notificationsEnabled && !isPolicyBlocked && !notificationSettingsLoading}
    <p class="text-muted px-5 pb-4 text-xs">
      {m.api_keys_notifications_enable_to_edit_hint()}
    </p>
  {/if}

  <!-- Expanded body (only when enabled) -->
  {#if notificationsEnabled && !isPolicyBlocked}
    <div class="border-default space-y-4 border-t px-5 py-4" transition:slide={{ duration: 200 }}>
      <p class="text-secondary text-xs">
        {m.api_keys_notifications_settings_description()}
      </p>

      <!-- Reminder schedule -->
      <div
        class="space-y-3"
        class:opacity-50={notificationSettingsSaving}
        class:pointer-events-none={notificationSettingsSaving}
      >
        <!-- Quick day chips -->
        <div class="flex flex-wrap gap-1.5">
          {#each reminderDayOptions as day (day)}
            {@const isSelected = selectedReminderDays.includes(day)}
            <button
              type="button"
              style="font-variant-numeric: tabular-nums"
              class="focus-visible:ring-accent-default/50 inline-flex h-8 min-w-[42px] items-center justify-center rounded-lg px-3 text-xs font-medium transition-all focus-visible:ring-2 focus-visible:outline-none {isSelected
                ? 'bg-accent-default text-on-fill shadow-sm'
                : 'border-default bg-primary text-secondary hover:text-primary hover:border-stronger border'}"
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
            <Field.Field>
              <Field.Label for="notification-days-input">
                {m.api_keys_notifications_days_label()}
              </Field.Label>
              <Input
                id="notification-days-input"
                bind:value={notificationDaysInput}
                placeholder="30, 14, 7, 3, 1"
                disabled={notificationSettingsSaving}
                onblur={debouncedSaveDays}
              />
            </Field.Field>
          </div>
        {:else}
          <Button
            variant="link"
            size="sm"
            class="text-accent-default h-auto p-0"
            onclick={() => (showCustomInput = true)}
          >
            {m.api_keys_notifications_customize_days()}
          </Button>
        {/if}

        <p class="text-muted text-xs leading-relaxed">
          {m.api_keys_notifications_days_help()}
          {#if notificationPolicyMaxDays}
            {m.api_keys_notifications_max_days_hint({ days: notificationPolicyMaxDays })}
          {/if}
        </p>
      </div>

      <!-- Auto-follow settings -->
      <div
        class="border-default space-y-3 border-t pt-4"
        class:opacity-50={notificationSettingsSaving}
        class:pointer-events-none={notificationSettingsSaving}
      >
        <!-- Assistants -->
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <p class="text-primary text-sm font-medium">
              {m.api_keys_notifications_auto_follow_assistants_title()}
            </p>
            <p class="text-secondary mt-0.5 text-xs">
              {m.api_keys_notifications_auto_follow_assistants_description()}
            </p>
            {#if allowAutoFollowAssistants === false}
              <p class="text-negative-default mt-1 text-xs">
                {m.api_keys_notifications_auto_follow_assistants_locked_hint()}
              </p>
            {/if}
          </div>
          <div class="shrink-0 pt-0.5">
            <Switch
              checked={autoFollowPublishedAssistants}
              onCheckedChange={(next) =>
                handleAutoFollowAssistantsToggle({
                  current: autoFollowPublishedAssistants,
                  next
                })}
              disabled={notificationSettingsSaving || allowAutoFollowAssistants === false}
              aria-label={m.api_keys_notifications_auto_follow_assistants_title()}
            />
          </div>
        </div>

        <!-- Apps -->
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <p class="text-primary text-sm font-medium">
              {m.api_keys_notifications_auto_follow_apps_title()}
            </p>
            <p class="text-secondary mt-0.5 text-xs">
              {m.api_keys_notifications_auto_follow_apps_description()}
            </p>
            {#if allowAutoFollowApps === false}
              <p class="text-negative-default mt-1 text-xs">
                {m.api_keys_notifications_auto_follow_apps_locked_hint()}
              </p>
            {/if}
          </div>
          <div class="shrink-0 pt-0.5">
            <Switch
              checked={autoFollowPublishedApps}
              onCheckedChange={(next) =>
                handleAutoFollowAppsToggle({
                  current: autoFollowPublishedApps,
                  next
                })}
              disabled={notificationSettingsSaving || allowAutoFollowApps === false}
              aria-label={m.api_keys_notifications_auto_follow_apps_title()}
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
