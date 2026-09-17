<!--
  Tenant policy for embeddable widgets: the ceilings every widget in the
  organisation must stay within. Saved as you type.
-->
<script lang="ts">
  import type { WidgetPolicy, WidgetPolicyUpdate, WidgetTemplate } from "@eneo/eneo-js";
  import { Button, Dialog, Input } from "@eneo/ui";
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
        name: m.widget_admin_template_new_name(),
        is_default: templates.length === 0
      });
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- localized href built from a typed route segment
      await goto(localizeHref(`/admin/widgets/templates/${created.id}`));
    } catch (error) {
      toastError(error, m.widget_admin_template_could_not_create());
    }
  });

  async function setDefault(template: WidgetTemplate) {
    try {
      const updated = await data.eneo.widgets.templates.update({
        template: { id: template.id },
        update: { is_default: true }
      });
      templates = templates.map((t) =>
        t.id === updated.id ? updated : { ...t, is_default: false }
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

  const inputClass =
    "border-default bg-primary ring-default rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 w-full";

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
      <Settings.Group title={m.widget_admin_policy()}>
        <Settings.Row
          title={m.widget_admin_policy_max_active()}
          description={m.widget_admin_policy_max_active_description()}
          let:aria
        >
          <input
            type="number"
            class={inputClass}
            min="0"
            max="1000"
            {...aria}
            value={policy.max_active_widgets}
            oninput={(event) => number(event, (value) => patch({ max_active_widgets: value }))}
          />
        </Settings.Row>
        <Settings.Row
          title={m.widget_admin_policy_max_budget()}
          description={m.widget_admin_policy_max_budget_description()}
          let:aria
        >
          <input
            type="number"
            class={inputClass}
            min="1000"
            step="1000"
            {...aria}
            value={policy.max_daily_token_budget}
            oninput={(event) => number(event, (value) => patch({ max_daily_token_budget: value }))}
          />
        </Settings.Row>
        <Settings.Row
          title={m.widget_admin_policy_retention()}
          description={m.widget_admin_policy_retention_description()}
          let:aria
        >
          <div class="grid grid-cols-2 gap-3">
            <label class="flex flex-col gap-1 text-sm">
              {m.widget_admin_policy_retention_min()}
              <input
                type="number"
                class={inputClass}
                min="0"
                max="3650"
                {...aria}
                value={policy.min_retention_days}
                oninput={(event) => number(event, (value) => patch({ min_retention_days: value }))}
              />
            </label>
            <label class="flex flex-col gap-1 text-sm">
              {m.widget_admin_policy_retention_max()}
              <input
                type="number"
                class={inputClass}
                min="0"
                max="3650"
                value={policy.max_retention_days}
                oninput={(event) => number(event, (value) => patch({ max_retention_days: value }))}
              />
            </label>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.widget_admin_policy_allow_none()}
          description={m.widget_admin_policy_allow_none_description()}
        >
          <div class="border-default flex h-14 items-center border-b">
            <Input.Switch
              value={policy.allow_bot_protection_none}
              sideEffect={({ next }) => patch({ allow_bot_protection_none: next })}
            >
              {m.widget_admin_policy_allow_none()}
            </Input.Switch>
          </div>
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
              <Button
                variant="primary-outlined"
                onclick={createTemplate}
                disabled={createTemplate.isLoading}>{m.widget_admin_template_new()}</Button
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
                          {#if !template.is_default}
                            <Button variant="outlined" onclick={() => setDefault(template)}
                              >{m.widget_admin_template_set_default()}</Button
                            >
                          {/if}
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
