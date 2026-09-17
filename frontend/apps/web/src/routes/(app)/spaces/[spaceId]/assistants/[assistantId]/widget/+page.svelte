<script lang="ts">
  import type { Widget } from "@eneo/eneo-js";
  import { Button } from "@eneo/ui";
  import { Page } from "$lib/components/layout";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager.js";
  import WidgetEditor from "$lib/features/widget/admin/WidgetEditor.svelte";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  let widget = $state<Widget | null>(untrack(() => data.widget));
  let name = $state(untrack(() => data.assistant.name));
  let templateId = $state(untrack(() => data.templates.find((t) => t.is_default)?.id ?? ""));

  const create = createAsyncState(async () => {
    try {
      widget = await data.eneo.widgets.create({
        spaceId: data.currentSpace.id,
        target_id: data.assistant.id,
        name: name.trim() || data.assistant.name,
        language: "auto",
        template_id: templateId || null
      });
    } catch (error) {
      toastError(error, m.widget_admin_could_not_create());
    }
  });
</script>

<svelte:head>
  <title>Eneo.ai – {data.assistant.name} – {m.widget_admin_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: data.assistant.name,
        href: `/spaces/${$currentSpace.routeId}/assistants/${data.assistant.id}/edit`
      }}
      title={m.widget_admin_title()}
    ></Page.Title>
  </Page.Header>

  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1400px] flex-col gap-6 p-4">
      {#if widget}
        {#key widget.id}
          <WidgetEditor
            {widget}
            assistant={data.assistant}
            eneo={data.eneo}
            isAdmin={data.isAdmin}
            policy={data.policy}
            release={data.release}
            templates={data.templates}
          />
        {/key}
      {:else}
        <section
          aria-labelledby="widget-create-title"
          class="border-default bg-primary mx-auto flex w-full max-w-xl flex-col gap-4 rounded-xl border p-6"
        >
          <h2 id="widget-create-title" class="text-lg font-semibold">
            {m.widget_admin_create_title()}
          </h2>
          <p class="text-secondary text-sm">{m.widget_admin_create_description()}</p>
          <form
            class="flex flex-col gap-3"
            onsubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <label class="flex flex-col gap-1 text-sm font-medium">
              {m.name()}
              <input
                type="text"
                class="border-default bg-primary ring-default rounded-lg border px-3 py-2 font-normal shadow focus-visible:ring-2"
                maxlength="100"
                required
                bind:value={name}
              />
            </label>
            {#if data.templates.length > 0}
              <label class="flex flex-col gap-1 text-sm font-medium">
                {m.widget_admin_template()}
                <select
                  class="border-default bg-primary ring-default rounded-lg border px-3 py-2 font-normal shadow focus-visible:ring-2"
                  bind:value={templateId}
                >
                  <option value="">{m.widget_admin_template_none()}</option>
                  {#each data.templates as template (template.id)}
                    <option value={template.id}>
                      {template.name}{template.is_default
                        ? ` (${m.widget_admin_template_default()})`
                        : ""}
                    </option>
                  {/each}
                </select>
                <span class="text-secondary text-xs font-normal"
                  >{m.widget_admin_template_create_help()}</span
                >
              </label>
            {/if}
            <div>
              <Button variant="primary" type="submit" disabled={create.isLoading}
                >{m.widget_admin_create()}</Button
              >
            </div>
          </form>
        </section>
      {/if}
    </div>
  </Page.Main>
</Page.Root>
