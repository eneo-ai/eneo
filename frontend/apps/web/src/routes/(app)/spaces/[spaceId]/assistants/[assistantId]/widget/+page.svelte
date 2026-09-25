<script lang="ts">
  import type { Widget } from "@eneo/eneo-js";
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager.js";
  import TemplatePicker from "$lib/features/widget/admin/TemplatePicker.svelte";
  import WidgetEditor from "$lib/features/widget/admin/WidgetEditor.svelte";
  import { m } from "$lib/paraglide/messages";
  import { tick, untrack } from "svelte";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  let widget = $state<Widget | null>(untrack(() => data.widget));
  let name = $state(untrack(() => data.assistant.name));
  // Widgets follow a template's published release, so drafts are not offered.
  const templates = $derived(data.templates.filter((t) => t.published_at != null));
  let templateId = $state(untrack(() => templates.find((t) => t.is_default)?.id ?? ""));

  // The archive dialog's trigger goes with the editor, so the focus it would
  // return there moves to the note saying what happened.
  let archived = $state(false);
  let archivedNote = $state<HTMLElement | null>(null);
  async function onArchived() {
    widget = null;
    archived = true;
    await tick();
    archivedNote?.focus();
  }

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
            currentUserId={data.user.id}
            policy={data.policy}
            release={data.release}
            {templates}
            {onArchived}
          />
        {/key}
      {:else}
        {#if archived}
          <p
            bind:this={archivedNote}
            tabindex="-1"
            class="bg-secondary mx-auto w-full max-w-3xl rounded-lg px-4 py-3 text-sm"
          >
            {m.widget_admin_archived_note()}
          </p>
        {/if}
        <Card.Root class="mx-auto w-full max-w-3xl">
          <Card.Header>
            <Card.Title><h2>{m.widget_admin_create_title()}</h2></Card.Title>
            <Card.Description
              >{data.isAdmin
                ? m.widget_admin_create_description_admin()
                : m.widget_admin_create_description()}</Card.Description
            >
          </Card.Header>
          <Card.Content>
            <form
              class="flex flex-col gap-6"
              onsubmit={(event) => {
                event.preventDefault();
                void create();
              }}
            >
              <Field.Field>
                <Field.Label for="widget-create-name">{m.name()}</Field.Label>
                <Input
                  id="widget-create-name"
                  maxlength={100}
                  required
                  bind:value={name}
                  aria-describedby="widget-create-name-help"
                />
                <Field.Description id="widget-create-name-help"
                  >{m.widget_admin_name_description()}</Field.Description
                >
              </Field.Field>
              {#if templates.length > 0}
                <Field.Field>
                  <Field.Title>{m.widget_admin_template()}</Field.Title>
                  <Field.Description>{m.widget_admin_template_create_help()}</Field.Description>
                  <TemplatePicker
                    {templates}
                    bind:value={templateId}
                    includeNone
                    legend={m.widget_admin_template()}
                    id="widget-create-template"
                  />
                </Field.Field>
              {/if}
              <div>
                <Button type="submit" disabled={create.isLoading}>{m.widget_admin_create()}</Button>
              </div>
            </form>
          </Card.Content>
        </Card.Root>
      {/if}
    </div>
  </Page.Main>
</Page.Root>
