<!--
  Tenant policy for embeddable widgets: the ceilings every widget in the
  organisation must stay within. Saved as you type.
-->
<script lang="ts">
  import type { WidgetPolicy, WidgetPolicyUpdate, WidgetTemplate } from "@eneo/eneo-js";
  import WidgetOverviewTable from "$lib/features/widget/admin/WidgetOverviewTable.svelte";
  import { Dialog } from "@eneo/ui";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { goto } from "$app/navigation";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { Page, Settings } from "$lib/components/layout";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { writable } from "svelte/store";

  let { data } = $props();

  let policy = $state<WidgetPolicy>(untrack(() => data.policy));
  let templates = $state<WidgetTemplate[]>(untrack(() => data.templates));
  let templateToDelete = $state<WidgetTemplate | null>(null);
  const showDelete = writable(false);

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
      $showDelete = false;
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

  function number(event: Event, apply: (value: number) => void) {
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
    <Settings.Page>
      <Settings.Group title={m.widget_admin_overview()}>
        <Settings.Row
          title={m.widget_admin_overview()}
          description={m.widget_admin_overview_description()}
          fullWidth
        >
          <WidgetOverviewTable overview={data.overview} />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.widget_admin_policy()}>
        <Settings.Row
          title={m.widget_admin_policy()}
          description={m.widget_admin_policy_description()}
          fullWidth
        >
          <Card.Root>
            <Card.Content>
              <Field.Group class="grid gap-6 sm:grid-cols-2">
                <Field.Field>
                  <Field.Label for="policy-max-budget"
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
                      number(event, (value) => patch({ max_daily_token_budget: value }))}
                  />
                  <Field.Description id="policy-max-budget-help"
                    >{m.widget_admin_policy_max_budget_description()}</Field.Description
                  >
                </Field.Field>
                <Field.Field>
                  <Field.Title>{m.widget_admin_policy_retention()}</Field.Title>
                  <div class="grid grid-cols-2 gap-3">
                    <Field.Field>
                      <Field.Label for="policy-retention-min"
                        >{m.widget_admin_policy_retention_min()}</Field.Label
                      >
                      <Input
                        id="policy-retention-min"
                        type="number"
                        min={0}
                        max={3650}
                        value={policy.min_retention_days}
                        oninput={(event) =>
                          number(event, (value) => patch({ min_retention_days: value }))}
                      />
                    </Field.Field>
                    <Field.Field>
                      <Field.Label for="policy-retention-max"
                        >{m.widget_admin_policy_retention_max()}</Field.Label
                      >
                      <Input
                        id="policy-retention-max"
                        type="number"
                        min={0}
                        max={3650}
                        value={policy.max_retention_days}
                        oninput={(event) =>
                          number(event, (value) => patch({ max_retention_days: value }))}
                      />
                    </Field.Field>
                  </div>
                  <Field.Description
                    >{m.widget_admin_policy_retention_description()}</Field.Description
                  >
                </Field.Field>
                <Field.Field orientation="horizontal" class="sm:col-span-2">
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
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.widget_admin_templates()}>
        <Settings.Row
          title={m.widget_admin_templates()}
          description={m.widget_admin_templates_description()}
          fullWidth
        >
          <div class="flex flex-col gap-3">
            <div>
              <Button variant="outline" onclick={createTemplate} disabled={createTemplate.isLoading}
                >{m.widget_admin_template_new()}</Button
              >
            </div>
            {#if templates.length === 0}
              <p class="text-secondary text-sm">{m.widget_admin_templates_empty()}</p>
            {:else}
              <Table.Root>
                <caption class="sr-only">{m.widget_admin_templates()}</caption>
                <Table.Header>
                  <Table.Row>
                    <Table.Head>{m.name()}</Table.Head>
                    <Table.Head>{m.widget_admin_language()}</Table.Head>
                    <Table.Head class="text-right">{m.actions()}</Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {#each templates as template (template.id)}
                    <Table.Row>
                      <Table.Cell>
                        <div class="flex items-center gap-2">
                          <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed route segment -->
                          <a
                            class="font-medium underline-offset-2 hover:underline"
                            href={localizeHref(`/admin/widgets/templates/${template.id}`)}
                            >{template.name}</a
                          >
                          <!-- eslint-enable svelte/no-navigation-without-resolve -->
                          {#if template.is_default}
                            <Badge variant="outline">{m.widget_admin_template_default()}</Badge>
                          {/if}
                        </div>
                        {#if template.description}
                          <p class="text-secondary text-sm">{template.description}</p>
                        {/if}
                      </Table.Cell>
                      <Table.Cell>{languageLabel(template.language)}</Table.Cell>
                      <Table.Cell class="text-right">
                        <div class="flex justify-end gap-2">
                          <Button
                            variant="outline"
                            onclick={() => setDefault(template, !template.is_default)}
                            >{template.is_default
                              ? m.widget_admin_template_unset_default()
                              : m.widget_admin_template_set_default()}</Button
                          >
                          <Button
                            variant="destructive"
                            onclick={() => {
                              templateToDelete = template;
                              $showDelete = true;
                            }}
                            aria-label={m.widget_admin_template_delete_named({
                              name: template.name
                            })}>{m.delete()}</Button
                          >
                        </div>
                      </Table.Cell>
                    </Table.Row>
                  {/each}
                </Table.Body>
              </Table.Root>
            {/if}
          </div>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<Dialog.Root openController={showDelete}>
  <Dialog.Content>
    <Dialog.Title>{m.widget_admin_template_delete_title()}</Dialog.Title>
    <Dialog.Description>{m.widget_admin_template_delete_description()}</Dialog.Description>
    <Dialog.Controls>
      <Button onclick={() => ($showDelete = false)}>{m.cancel()}</Button>
      <Button variant="destructive" onclick={deleteTemplate} disabled={deleteTemplate.isLoading}
        >{m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
