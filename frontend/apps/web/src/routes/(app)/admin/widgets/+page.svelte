<!--
  Admin → Webbwidgetar. Three concerns, one tab each: the organisation's
  widgets and how they are used, the policy every widget must stay within,
  and the templates editors start from.
-->
<script lang="ts">
  import type { WidgetPolicy, WidgetPolicyUpdate, WidgetTemplate } from "@eneo/eneo-js";
  import { beforeNavigate, goto } from "$app/navigation";
  import {
    LayoutGrid,
    Pencil,
    Plus,
    ShieldCheck,
    Star,
    StarOff,
    SwatchBook,
    Trash2
  } from "lucide-svelte";
  import { Page } from "$lib/components/layout";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { toastError } from "$lib/core/errors";
  import { toastWidgetError } from "$lib/features/widget/admin/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import WidgetOverviewList from "$lib/features/widget/admin/WidgetOverviewList.svelte";
  import { urlTab } from "$lib/features/widget/admin/tabState.svelte";
  import { Autosave } from "$lib/features/widget/admin/widgetAutosave.svelte";
  import { DEFAULT_PRIMARY_COLOR, isHexColor } from "$lib/features/widget/contrast";
  import { m } from "$lib/paraglide/messages";
  import { getLocale, localizeHref } from "$lib/paraglide/runtime";
  import { untrack } from "svelte";

  let { data } = $props();

  const number = new Intl.NumberFormat(getLocale());

  // --- policy (saved as you type) -------------------------------------------
  // The shared autosave serialises saves and keeps edits made while one is in
  // flight, so a slow response never reverts a newer value on screen or on
  // the server (the API stores the policy document whole).
  const autosave = untrack(
    () =>
      new Autosave<WidgetPolicy, WidgetPolicyUpdate>(data.policy, async (update) => {
        try {
          return await data.eneo.widgets.policy.update(update);
        } catch (error) {
          toastError(error, m.widget_admin_save_failed());
          throw error;
        }
      })
  );

  beforeNavigate((navigation) => {
    if (autosave.stranded && !confirm(m.widget_admin_unsaved_leave_confirm())) {
      navigation.cancel();
      return;
    }
    void autosave.flush();
  });

  const policy = $derived(autosave.widget);

  function patch(update: WidgetPolicyUpdate) {
    autosave.patch(update);
  }

  // Committed when the field is left, never per keystroke, and kept local
  // with an error while out of range instead of failing the save.
  let rangeErrors = $state<Record<string, string>>({});
  function commitNumber(
    event: Event,
    key: string,
    min: number,
    max: number,
    apply: (value: number) => void
  ) {
    const value = Number((event.currentTarget as HTMLInputElement).value);
    if (!Number.isInteger(value) || value < min || value > max) {
      rangeErrors = {
        ...rangeErrors,
        [key]: m.widget_admin_value_out_of_range({
          min: min.toLocaleString(),
          max: max.toLocaleString()
        })
      };
      return;
    }
    const { [key]: _cleared, ...rest } = rangeErrors;
    rangeErrors = rest;
    apply(value);
  }

  // The API refuses a retention window whose minimum exceeds its maximum. Both
  // bounds are kept as typed until the pair is valid, so fixing one bound
  // also settles the other, and the pair is saved together.
  let retentionTyped = $state<{ min: string | null; max: string | null }>({
    min: null,
    max: null
  });
  function commitRetention(event: Event, bound: "min" | "max") {
    retentionTyped = {
      ...retentionTyped,
      [bound]: (event.currentTarget as HTMLInputElement).value
    };
    const value = (side: "min" | "max") => {
      const typed = retentionTyped[side];
      if (typed !== null) return typed.trim() === "" ? NaN : Number(typed);
      return side === "min" ? policy.min_retention_days : policy.max_retention_days;
    };
    const errors: Partial<Record<"min" | "max", string>> = {};
    for (const side of ["min", "max"] as const) {
      const days = value(side);
      if (retentionTyped[side] !== null && (!Number.isInteger(days) || days < 0 || days > 3650)) {
        errors[side] = m.widget_admin_value_out_of_range({
          min: "0",
          max: (3650).toLocaleString()
        });
      }
    }
    if (!errors.min && !errors.max && value("min") > value("max")) {
      errors[bound] =
        bound === "min"
          ? m.widget_admin_retention_window_min({ max: String(value("max")) })
          : m.widget_admin_retention_window_max({ min: String(value("min")) });
    }
    const { "retention-min": _min, "retention-max": _max, ...others } = rangeErrors;
    rangeErrors = {
      ...others,
      ...(errors.min ? { "retention-min": errors.min } : {}),
      ...(errors.max ? { "retention-max": errors.max } : {})
    };
    if (errors.min || errors.max) return;
    const update: WidgetPolicyUpdate = {};
    if (value("min") !== policy.min_retention_days) update.min_retention_days = value("min");
    if (value("max") !== policy.max_retention_days) update.max_retention_days = value("max");
    retentionTyped = { min: null, max: null };
    if (Object.keys(update).length > 0) patch(update);
  }

  // Out-of-range numbers stay in their fields; leaving the page asks first.
  $effect(() => {
    autosave.markDraft("policy-numbers", Object.keys(rangeErrors).length > 0);
  });

  const statusLabel = $derived.by(() => {
    switch (autosave.status) {
      case "saving":
        return m.widget_admin_saving();
      case "saved":
        return m.widget_admin_saved();
      case "error":
      case "conflict":
        return m.widget_admin_save_failed();
      case "refused":
        return m.widget_admin_save_refused();
      default:
        return "";
    }
  });

  // --- templates --------------------------------------------------------------
  let templates = $state<WidgetTemplate[]>(untrack(() => data.templates));
  let templateToDelete = $state<WidgetTemplate | null>(null);
  let deleteOpen = $state(false);

  const createTemplate = createAsyncState(async () => {
    try {
      const created = await data.eneo.widgets.templates.create({
        name: m.widget_admin_template_new_name()
      });
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- localized href built from a typed route segment
      await goto(localizeHref(`/admin/widgets/templates/${created.id}`));
    } catch (error) {
      toastError(error, m.widget_admin_template_could_not_create());
    }
  });

  async function setDefault(template: WidgetTemplate, isDefault: boolean) {
    try {
      const updated = await data.eneo.widgets.templates.update({
        template: { id: template.id },
        update: { is_default: isDefault }
      });
      templates = templates.map((t) =>
        t.id === updated.id ? updated : isDefault ? { ...t, is_default: false } : t
      );
    } catch (error) {
      toastError(error, m.widget_admin_save_failed());
    }
  }

  const deleteTemplate = createAsyncState(async () => {
    const target = templateToDelete;
    if (!target) return;
    try {
      await data.eneo.widgets.templates.delete({ id: target.id });
      templates = templates.filter((t) => t.id !== target.id);
      deleteOpen = false;
      templateToDelete = null;
    } catch (error) {
      toastWidgetError(error, m.widget_admin_template_could_not_delete());
    }
  });

  function languageLabel(language: WidgetTemplate["language"]) {
    return language === "sv"
      ? m.widget_admin_language_sv()
      : language === "en"
        ? m.widget_admin_language_en()
        : m.widget_admin_language_auto();
  }

  function accent(template: WidgetTemplate) {
    const colour = template.theme.primary_color ?? "";
    return isHexColor(colour) ? colour : DEFAULT_PRIMARY_COLOR;
  }
  function header(template: WidgetTemplate) {
    const colour = template.theme.header_color ?? "";
    return isHexColor(colour) ? colour : null;
  }

  const totals = $derived(data.overview.totals);
  const tab = urlTab(["widgets", "policy", "templates"] as const, "widgets");
</script>

<svelte:window
  onbeforeunload={(event) => {
    if (autosave.unsaved) event.preventDefault();
  }}
/>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.widget_admin_nav()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.widget_admin_nav()}></Page.Title>
    <Page.Flex>
      <span class="text-secondary text-sm" aria-live="polite" aria-atomic="true">{statusLabel}</span
      >
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1400px] flex-col gap-6 p-4">
      <Tabs.Root bind:value={tab.value} class="gap-6">
        <Tabs.List
          class="h-auto w-full flex-wrap gap-1 p-1 sm:w-auto"
          aria-label={m.widget_admin_nav()}
        >
          <Tabs.Trigger value="widgets" class="h-9 px-3">
            <LayoutGrid aria-hidden="true" />
            {m.widget_admin_tab_widgets()}
            <Badge variant="secondary" class="ml-1">{number.format(totals.widgets)}</Badge>
          </Tabs.Trigger>
          <Tabs.Trigger value="policy" class="h-9 px-3">
            <ShieldCheck aria-hidden="true" />
            {m.widget_admin_tab_policy()}
          </Tabs.Trigger>
          <Tabs.Trigger value="templates" class="h-9 px-3">
            <SwatchBook aria-hidden="true" />
            {m.widget_admin_templates()}
            <Badge variant="secondary" class="ml-1">{number.format(templates.length)}</Badge>
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="widgets" class="flex flex-col gap-6">
          <p class="text-secondary max-w-[72ch] text-sm">{m.widget_admin_overview_description()}</p>
          <!-- Plain list: a dl may only wrap dt/dd in a single div, which the cards are not. -->
          <ul class="grid grid-cols-2 gap-3 md:grid-cols-4">
            <li>
              <Card.Root size="sm" class="h-full">
                <Card.Content>
                  <p class="text-secondary text-xs">{m.widget_admin_stat_widgets()}</p>
                  <p class="text-2xl font-semibold tabular-nums">
                    {number.format(totals.widgets)}
                    <span class="text-secondary text-sm font-normal">
                      {m.widget_admin_stat_active({ count: number.format(totals.active) })}
                    </span>
                  </p>
                </Card.Content>
              </Card.Root>
            </li>
            <li>
              <Card.Root size="sm" class="h-full">
                <Card.Content>
                  <p class="text-secondary text-xs">{m.widget_admin_overview_questions_30d()}</p>
                  <p class="text-2xl font-semibold tabular-nums">
                    {number.format(totals.questions_30d)}
                  </p>
                </Card.Content>
              </Card.Root>
            </li>
            <li>
              <Card.Root size="sm" class="h-full">
                <Card.Content>
                  <p class="text-secondary text-xs">{m.widget_admin_overview_tokens_30d()}</p>
                  <p class="text-2xl font-semibold tabular-nums">
                    {number.format(totals.tokens_30d)}
                  </p>
                </Card.Content>
              </Card.Root>
            </li>
            <li>
              <Card.Root size="sm" class="h-full">
                <Card.Content>
                  <p class="text-secondary text-xs">{m.widget_admin_overview_blocked_30d()}</p>
                  <p
                    class={[
                      "text-2xl font-semibold tabular-nums",
                      totals.blocked_30d > 0 && "text-warning-stronger"
                    ]}
                  >
                    {number.format(totals.blocked_30d)}
                  </p>
                </Card.Content>
              </Card.Root>
            </li>
          </ul>
          <WidgetOverviewList overview={data.overview} eneo={data.eneo} />
        </Tabs.Content>

        <Tabs.Content value="policy">
          <Card.Root>
            <Card.Header>
              <Card.Title><h2>{m.widget_admin_policy()}</h2></Card.Title>
              <Card.Description>{m.widget_admin_policy_description()}</Card.Description>
            </Card.Header>
            <Card.Content>
              <Field.Group class="grid gap-6 md:grid-cols-3">
                <Field.Field>
                  <Field.Label for="policy-max-budget" class="min-h-10 items-end"
                    >{m.widget_admin_policy_max_budget()}</Field.Label
                  >
                  <Input
                    id="policy-max-budget"
                    type="number"
                    min={1000}
                    step={1000}
                    value={policy.max_daily_token_budget}
                    aria-invalid={!!rangeErrors.budget}
                    aria-describedby={rangeErrors.budget
                      ? "policy-max-budget-help policy-max-budget-error"
                      : "policy-max-budget-help"}
                    onchange={(event) =>
                      commitNumber(event, "budget", 1000, 100_000_000, (value) =>
                        patch({ max_daily_token_budget: value })
                      )}
                  />
                  <Field.Description id="policy-max-budget-help"
                    >{m.widget_admin_policy_max_budget_description()}</Field.Description
                  >
                  {#if rangeErrors.budget}
                    <Field.Error id="policy-max-budget-error">{rangeErrors.budget}</Field.Error>
                  {/if}
                </Field.Field>
                <Field.Field>
                  <Field.Label for="policy-retention-min" class="min-h-10 items-end"
                    >{m.widget_admin_policy_retention_min()}</Field.Label
                  >
                  <Input
                    id="policy-retention-min"
                    type="number"
                    min={0}
                    max={3650}
                    value={policy.min_retention_days}
                    aria-invalid={!!rangeErrors["retention-min"]}
                    aria-describedby={rangeErrors["retention-min"]
                      ? "policy-retention-help policy-retention-min-error"
                      : "policy-retention-help"}
                    onchange={(event) => commitRetention(event, "min")}
                  />
                  <Field.Description id="policy-retention-help"
                    >{m.widget_admin_policy_retention_description()}</Field.Description
                  >
                  {#if rangeErrors["retention-min"]}
                    <Field.Error id="policy-retention-min-error"
                      >{rangeErrors["retention-min"]}</Field.Error
                    >
                  {/if}
                </Field.Field>
                <Field.Field>
                  <Field.Label for="policy-retention-max" class="min-h-10 items-end"
                    >{m.widget_admin_policy_retention_max()}</Field.Label
                  >
                  <Input
                    id="policy-retention-max"
                    type="number"
                    min={0}
                    max={3650}
                    value={policy.max_retention_days}
                    aria-invalid={!!rangeErrors["retention-max"]}
                    aria-describedby={rangeErrors["retention-max"]
                      ? "policy-retention-help policy-retention-max-error"
                      : "policy-retention-help"}
                    onchange={(event) => commitRetention(event, "max")}
                  />
                  {#if rangeErrors["retention-max"]}
                    <Field.Error id="policy-retention-max-error"
                      >{rangeErrors["retention-max"]}</Field.Error
                    >
                  {/if}
                </Field.Field>
                <Field.Separator class="md:col-span-3" />
                <Field.Field orientation="horizontal" class="md:col-span-3">
                  <Field.Content>
                    <Field.Label for="policy-allow-none"
                      >{m.widget_admin_policy_allow_none()}</Field.Label
                    >
                    <Field.Description id="policy-allow-none-help"
                      >{m.widget_admin_policy_allow_none_description()}</Field.Description
                    >
                  </Field.Content>
                  <Switch
                    id="policy-allow-none"
                    aria-describedby="policy-allow-none-help"
                    checked={policy.allow_bot_protection_none}
                    onCheckedChange={(checked) => patch({ allow_bot_protection_none: checked })}
                  />
                </Field.Field>
              </Field.Group>
            </Card.Content>
          </Card.Root>
        </Tabs.Content>

        <Tabs.Content value="templates">
          <Card.Root>
            <Card.Header class="border-b">
              <Card.Title><h2>{m.widget_admin_templates()}</h2></Card.Title>
              <Card.Description>{m.widget_admin_templates_description()}</Card.Description>
              <Card.Action>
                <Button onclick={createTemplate} disabled={createTemplate.isLoading}>
                  <Plus aria-hidden="true" data-icon="inline-start" />
                  {m.widget_admin_template_new()}
                </Button>
              </Card.Action>
            </Card.Header>
            <Card.Content>
              {#if templates.length === 0}
                <p class="text-secondary text-sm">{m.widget_admin_templates_empty()}</p>
              {:else}
                <ul class="divide-default -mx-4 divide-y" aria-label={m.widget_admin_templates()}>
                  {#each templates as template (template.id)}
                    <li class="flex flex-wrap items-center gap-4 px-4 py-4">
                      <span class="flex shrink-0 items-center gap-1" aria-hidden="true">
                        <span
                          class="border-default inline-block h-8 w-8 rounded-full border"
                          style:background={accent(template)}
                        ></span>
                        <span
                          class="border-default inline-block h-8 w-5 rounded-md border"
                          style:background={header(template) ?? "transparent"}
                        ></span>
                      </span>
                      <div class="min-w-0 flex-1">
                        <div class="flex flex-wrap items-center gap-2">
                          <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed route segment -->
                          <a
                            class="font-medium underline-offset-2 hover:underline"
                            href={localizeHref(`/admin/widgets/templates/${template.id}`)}
                            >{template.name}</a
                          >
                          <!-- eslint-enable svelte/no-navigation-without-resolve -->
                          {#if template.is_default}
                            <Badge>{m.widget_admin_template_default()}</Badge>
                          {/if}
                          {#if template.published_at == null}
                            <Badge variant="outline">{m.widget_admin_template_unpublished()}</Badge>
                          {:else if template.has_unpublished_changes}
                            <Badge variant="outline">
                              {m.widget_admin_template_unpublished_changes()}
                            </Badge>
                          {/if}
                          {#if template.linked_widgets > 0}
                            <Badge variant="secondary">
                              {template.linked_widgets === 1
                                ? m.widget_admin_template_linked_count_one()
                                : m.widget_admin_template_linked_count({
                                    count: number.format(template.linked_widgets)
                                  })}
                            </Badge>
                          {/if}
                          <span class="text-secondary text-xs"
                            >{languageLabel(template.language)}</span
                          >
                        </div>
                        {#if template.description}
                          <p class="text-secondary text-sm">{template.description}</p>
                        {/if}
                      </div>
                      <div class="flex flex-wrap items-center gap-2">
                        <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed route segment -->
                        <Button
                          variant="outline"
                          size="sm"
                          href={localizeHref(`/admin/widgets/templates/${template.id}`)}
                        >
                          <Pencil aria-hidden="true" data-icon="inline-start" />
                          {m.edit()}
                        </Button>
                        <!-- eslint-enable svelte/no-navigation-without-resolve -->
                        <Button
                          variant="outline"
                          size="sm"
                          onclick={() => setDefault(template, !template.is_default)}
                        >
                          {#if template.is_default}
                            <StarOff aria-hidden="true" data-icon="inline-start" />
                            {m.widget_admin_template_unset_default()}
                          {:else}
                            <Star aria-hidden="true" data-icon="inline-start" />
                            {m.widget_admin_template_set_default()}
                          {/if}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          class="text-negative-default hover:text-negative-default"
                          onclick={() => {
                            templateToDelete = template;
                            deleteOpen = true;
                          }}
                          aria-label={m.widget_admin_template_delete_named({
                            name: template.name
                          })}
                        >
                          <Trash2 aria-hidden="true" data-icon="inline-start" />
                          {m.delete()}
                        </Button>
                      </div>
                    </li>
                  {/each}
                </ul>
              {/if}
            </Card.Content>
          </Card.Root>
        </Tabs.Content>
      </Tabs.Root>
    </div>
  </Page.Main>
</Page.Root>

<AlertDialog.Root bind:open={deleteOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.widget_admin_template_delete_title()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.widget_admin_template_delete_description()}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={deleteTemplate.isLoading}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        class="bg-negative-default text-on-fill"
        disabled={deleteTemplate.isLoading}
        onclick={(event) => {
          event.preventDefault();
          void deleteTemplate();
        }}>{m.delete()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
