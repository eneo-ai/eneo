<!--
  Tenant policy for embeddable widgets: the ceilings every widget in the
  organisation must stay within. Saved as you type.
-->
<script lang="ts">
  import type { WidgetPolicy, WidgetPolicyUpdate } from "@eneo/eneo-js";
  import { Input } from "@eneo/ui";
  import { Page, Settings } from "$lib/components/layout";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";

  let { data } = $props();

  let policy = $state<WidgetPolicy>(untrack(() => data.policy));
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
    </Settings.Page>
  </Page.Main>
</Page.Root>
