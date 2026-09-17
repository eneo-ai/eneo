<!--
  Admin → Webbwidgetar. Three concerns, one tab each: the organisation's
  widgets and how they are used, the policy every widget must stay within,
  and the templates editors start from.
-->
<script lang="ts">
  import type { WidgetPolicy, WidgetPolicyUpdate, WidgetTemplate } from "@eneo/eneo-js";
  import { goto } from "$app/navigation";
  import { Plus } from "lucide-svelte";
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
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import WidgetOverviewList from "$lib/features/widget/admin/WidgetOverviewList.svelte";
  import { DEFAULT_PRIMARY_COLOR, isHexColor } from "$lib/features/widget/contrast";
  import { m } from "$lib/paraglide/messages";
  import { getLocale, localizeHref } from "$lib/paraglide/runtime";
  import { untrack } from "svelte";

  let { data } = $props();

  const number = new Intl.NumberFormat(getLocale());

  // --- policy (saved as you type) -------------------------------------------
  let policy = $state<WidgetPolicy>(untrack(() => data.policy));
  let status = $state<"idle" | "saving" | "saved" | "error">("idle");
  let pending: WidgetPolicyUpdate = {};
  let timer: ReturnType<typeof setTimeout> | null = null;

  function patch(update: WidgetPolicyUpdate) {
    policy = { ...policy, ...(update as Partial<WidgetPolicy>) };
    pending = { ...pending, ...update };
    if (timer) clearTimeout(timer);
    timer = setTimeout(save, 600);
  }

  async function save() {
    timer = null;
    const update = pending;
    pending = {};
    status = "saving";
    try {
      policy = await data.eneo.widgets.policy.update(update);
      status = "saved";
    } catch (error) {
      pending = { ...update, ...pending };
      status = "error";
      toastError(error, m.widget_admin_save_failed());
    }
  }

  function numberInput(event: Event, apply: (value: number) => void) {
    const value = Number((event.currentTarget as HTMLInputElement).value);
    if (Number.isFinite(value)) apply(value);
  }

  const statusLabel = $derived(
    status === "saving"
      ? m.widget_admin_saving()
      : status === "saved"
        ? m.widget_admin_saved()
        : status === "error"
          ? m.widget_admin_save_failed()
          : ""
  );

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
      toastError(error, m.widget_admin_template_could_not_delete());
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
</script>

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
      <Tabs.Root value="widgets" class="gap-6">
        <Tabs.List variant="line" class="w-full justify-start">
          <Tabs.Trigger value="widgets">{m.widget_admin_tab_widgets()}</Tabs.Trigger>
          <Tabs.Trigger value="policy">{m.widget_admin_tab_policy()}</Tabs.Trigger>
          <Tabs.Trigger value="templates">{m.widget_admin_templates()}</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="widgets" class="flex flex-col gap-6">
          <p class="text-secondary max-w-[72ch] text-sm">{m.widget_admin_overview_description()}</p>
          <dl class="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card.Root size="sm">
              <Card.Content>
                <dt class="text-secondary text-xs">{m.widget_admin_stat_widgets()}</dt>
                <dd class="text-2xl font-semibold tabular-nums">
                  {number.format(totals.widgets)}
                  <span class="text-secondary text-sm font-normal">
                    {m.widget_admin_stat_active({ count: number.format(totals.active) })}
                  </span>
                </dd>
              </Card.Content>
            </Card.Root>
            <Card.Root size="sm">
              <Card.Content>
                <dt class="text-secondary text-xs">{m.widget_admin_overview_questions_30d()}</dt>
                <dd class="text-2xl font-semibold tabular-nums">
                  {number.format(totals.questions_30d)}
                </dd>
              </Card.Content>
            </Card.Root>
            <Card.Root size="sm">
              <Card.Content>
                <dt class="text-secondary text-xs">{m.widget_admin_overview_tokens_30d()}</dt>
                <dd class="text-2xl font-semibold tabular-nums">
                  {number.format(totals.tokens_30d)}
                </dd>
              </Card.Content>
            </Card.Root>
            <Card.Root size="sm">
              <Card.Content>
                <dt class="text-secondary text-xs">{m.widget_admin_overview_blocked_30d()}</dt>
                <dd
                  class={[
                    "text-2xl font-semibold tabular-nums",
                    totals.blocked_30d > 0 && "text-warning-stronger"
                  ]}
                >
                  {number.format(totals.blocked_30d)}
                </dd>
              </Card.Content>
            </Card.Root>
          </dl>
          <WidgetOverviewList overview={data.overview} />
        </Tabs.Content>

        <Tabs.Content value="policy">
          <Card.Root>
            <Card.Header>
              <Card.Title>{m.widget_admin_policy()}</Card.Title>
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
                    aria-describedby="policy-max-budget-help"
                    oninput={(event) =>
                      numberInput(event, (value) => patch({ max_daily_token_budget: value }))}
                  />
                  <Field.Description id="policy-max-budget-help"
                    >{m.widget_admin_policy_max_budget_description()}</Field.Description
                  >
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
                    aria-describedby="policy-retention-help"
                    oninput={(event) =>
                      numberInput(event, (value) => patch({ min_retention_days: value }))}
                  />
                  <Field.Description id="policy-retention-help"
                    >{m.widget_admin_policy_retention_description()}</Field.Description
                  >
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
                    aria-describedby="policy-retention-help"
                    oninput={(event) =>
                      numberInput(event, (value) => patch({ max_retention_days: value }))}
                  />
                </Field.Field>
                <Field.Separator class="md:col-span-3" />
                <Field.Field orientation="horizontal" class="md:col-span-3">
                  <Field.Content>
                    <Field.Label for="policy-allow-none"
                      >{m.widget_admin_policy_allow_none()}</Field.Label
                    >
                    <Field.Description
                      >{m.widget_admin_policy_allow_none_description()}</Field.Description
                    >
                  </Field.Content>
                  <Switch
                    id="policy-allow-none"
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
              <Card.Title>{m.widget_admin_templates()}</Card.Title>
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
                          >{m.edit()}</Button
                        >
                        <!-- eslint-enable svelte/no-navigation-without-resolve -->
                        <Button
                          variant="ghost"
                          size="sm"
                          onclick={() => setDefault(template, !template.is_default)}
                          >{template.is_default
                            ? m.widget_admin_template_unset_default()
                            : m.widget_admin_template_set_default()}</Button
                        >
                        <Button
                          variant="ghost"
                          size="sm"
                          class="text-negative-default"
                          onclick={() => {
                            templateToDelete = template;
                            deleteOpen = true;
                          }}
                          aria-label={m.widget_admin_template_delete_named({
                            name: template.name
                          })}>{m.delete()}</Button
                        >
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
