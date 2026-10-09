<!--
  Edit one widget template: the house style editors copy onto new widgets.
  Autosaved like the widget page; a static preview shows the result.
-->
<script lang="ts">
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { toastWidgetError } from "$lib/features/widget/admin/errors";
  import { WidgetTemplateAutosave } from "$lib/features/widget/admin/widgetAutosave.svelte";
  import { guardAutosaveNavigation } from "$lib/features/widget/admin/guardAutosaveNavigation";
  import WidgetMockPreview from "$lib/features/widget/admin/WidgetMockPreview.svelte";
  import WidgetTextsFields from "$lib/features/widget/admin/WidgetTextsFields.svelte";
  import WidgetThemeFields from "$lib/features/widget/admin/WidgetThemeFields.svelte";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { LOCK_GROUPS, publicationSummary } from "$lib/features/widget/admin/templateLocks";
  import { collapseWhitespace, TextDraft } from "$lib/features/widget/admin/textDraft.svelte";
  import { m } from "$lib/paraglide/messages";
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import { FileText, Palette } from "@lucide/svelte";
  import { untrack } from "svelte";

  let { data } = $props();

  const autosave = untrack(
    () =>
      new WidgetTemplateAutosave(data.template, async (update) => {
        try {
          return await data.eneo.widgets.templates.update({
            template: { id: data.template.id },
            update
          });
        } catch (error) {
          toastWidgetError(error, m.widget_admin_save_failed());
          throw error;
        }
      })
  );

  // SvelteKit reuses this component when only the id changes (history
  // navigation between two templates); the form must follow the new data.
  let loadedId = untrack(() => data.template.id);
  $effect(() => {
    if (data.template.id !== loadedId) {
      loadedId = data.template.id;
      autosave.reload(data.template);
    }
  });

  guardAutosaveNavigation(autosave);

  const template = $derived(autosave.widget);

  const name = new TextDraft(() => autosave.widget.name);
  const description = new TextDraft(() => autosave.widget.description ?? "");
  const nameProblem = $derived(
    !collapseWhitespace(name.text) ? m.widget_admin_name_required() : autosave.refusals["name"]
  );
  const textErrors = $derived(
    Object.fromEntries(
      Object.entries(autosave.refusals)
        .filter(([path]) => path.startsWith("texts."))
        .map(([path, message]) => [path.slice("texts.".length), message])
    )
  );
  // The legal-texts lock needs a subtitle to enforce; the API refuses the
  // save otherwise, so the switch waits until there is one.
  const hasSubtitle = $derived((template.texts.subtitle ?? "").trim().length > 0);

  const statusLabel = $derived(
    autosave.status === "saving"
      ? m.widget_admin_saving()
      : autosave.status === "saved"
        ? m.widget_admin_saved()
        : autosave.status === "error"
          ? m.widget_admin_save_failed()
          : autosave.status === "refused"
            ? m.widget_admin_save_refused()
            : ""
  );

  const languageLabels = $derived({
    auto: m.widget_admin_language_auto(),
    sv: m.widget_admin_language_sv(),
    en: m.widget_admin_language_en()
  });

  const lockLabels = $derived({
    appearance: {
      label: m.widget_admin_template_lock_appearance(),
      description: m.widget_admin_template_lock_appearance_description()
    },
    language: {
      label: m.widget_admin_template_lock_language(),
      description: m.widget_admin_template_lock_language_description()
    },
    legal_texts: {
      label: m.widget_admin_template_lock_legal_texts(),
      description: m.widget_admin_template_lock_legal_texts_description()
    },
    wording: {
      label: m.widget_admin_template_lock_wording(),
      description: m.widget_admin_template_lock_wording_description()
    }
  });
  const linkedLabel = $derived(
    template.linked_widgets === 0
      ? m.widget_admin_template_linked_none()
      : template.linked_widgets === 1
        ? m.widget_admin_template_linked_count_one()
        : m.widget_admin_template_linked_count({ count: String(template.linked_widgets) })
  );

  function setLock(group: (typeof LOCK_GROUPS)[number], locked: boolean) {
    autosave.patch({
      locked_groups: LOCK_GROUPS.filter((candidate) =>
        candidate === group ? locked : template.locked_groups.includes(candidate)
      )
    });
  }

  // Saving edits the draft; publishing is the deliberate step that reaches
  // the widgets. With followers it asks first, since their values change.
  const dateFormat = new Intl.DateTimeFormat(intlLocale(), {
    dateStyle: "medium",
    timeStyle: "short"
  });
  const publicationLabel = $derived(
    template.published_at == null
      ? m.widget_admin_template_unpublished()
      : template.has_unpublished_changes
        ? m.widget_admin_template_unpublished_changes()
        : m.widget_admin_template_published_at({
            date: dateFormat.format(new Date(template.published_at))
          })
  );
  let confirmPublish = $state(false);
  // The dialog names what the followers lose or regain, so an admin is not
  // confirming a count but a change.
  const summary = $derived(publicationSummary(template));
  const groupNames = (groups: (typeof LOCK_GROUPS)[number][]) =>
    groups.map((group) => lockLabels[group].label).join(", ");
  const changesNothing = $derived(
    summary.written.length === 0 &&
      summary.newlyLocked.length === 0 &&
      summary.released.length === 0
  );

  const publish = createAsyncState(async () => {
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      autosave.replace(await data.eneo.widgets.templates.publish({ id: data.template.id }));
      confirmPublish = false;
    } catch (error) {
      toastWidgetError(error, m.widget_admin_template_could_not_publish());
    }
  });

  function requestPublish() {
    if (template.linked_widgets > 0) confirmPublish = true;
    else void publish();
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.widget_admin_templates()} – {template.name}</title>
</svelte:head>

<svelte:window
  onbeforeunload={(event) => {
    if (autosave.unsaved) event.preventDefault();
  }}
/>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: m.widget_admin_templates(),
        href: `${resolve("/admin/widgets")}?tab=templates`
      }}
      title={template.name}
      truncate
    ></Page.Title>
    <Page.Flex>
      <span class="text-secondary text-sm" aria-live="polite" aria-atomic="true">{statusLabel}</span
      >
      <Badge
        id="template-publication-state"
        variant={template.has_unpublished_changes ? "default" : "secondary"}
      >
        {publicationLabel}
      </Badge>
      <!-- The visible badge explains the state; a title on a disabled button would not. -->
      <Button
        onclick={requestPublish}
        disabled={publish.isLoading || !template.has_unpublished_changes}
        aria-describedby="template-publication-state"
      >
        {m.widget_admin_template_publish()}
      </Button>
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    <div
      class="mx-auto grid w-full max-w-[1400px] gap-6 p-4 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]"
    >
      <div class="flex min-w-0 flex-col gap-6">
        <Card.Root>
          <Card.Header>
            <Card.Title><h2>{m.widget_admin_template_details()}</h2></Card.Title>
            <Card.Description>{m.widget_admin_template_name_description()}</Card.Description>
            <Card.Action>
              <Badge variant={template.linked_widgets > 0 ? "default" : "secondary"}>
                {linkedLabel}
              </Badge>
            </Card.Action>
          </Card.Header>
          <Card.Content>
            <p class="text-secondary text-sm">
              {template.published_at == null
                ? m.widget_admin_template_not_published_help()
                : m.widget_admin_template_publish_description()}
            </p>
          </Card.Content>
          <Card.Content>
            <Field.Group class="grid gap-6 sm:grid-cols-2">
              <Field.Field data-invalid={nameProblem ? true : undefined}>
                <Field.Label for="template-name">{m.name()}</Field.Label>
                <Input
                  id="template-name"
                  maxlength={100}
                  required
                  value={name.text}
                  aria-invalid={!!nameProblem}
                  aria-describedby={nameProblem ? "template-name-error" : undefined}
                  onfocus={name.focus}
                  onblur={name.blur}
                  oninput={(event) => {
                    name.text = event.currentTarget.value;
                    if (collapseWhitespace(name.text)) autosave.patch({ name: name.text });
                  }}
                />
                {#if nameProblem}
                  <Field.Error id="template-name-error">{nameProblem}</Field.Error>
                {/if}
              </Field.Field>
              <Field.Field>
                <Field.Label for="template-language">{m.widget_admin_language()}</Field.Label>
                <Select.Root
                  type="single"
                  value={template.language ?? "auto"}
                  onValueChange={(value) =>
                    autosave.patch({ language: value as typeof template.language })}
                >
                  <Select.Trigger id="template-language" class="w-full">
                    <span data-slot="select-value"
                      >{languageLabels[template.language ?? "auto"]}</span
                    >
                  </Select.Trigger>
                  <Select.Content>
                    {#each Object.entries(languageLabels) as [value, label] (value)}
                      <Select.Item {value} {label}>{label}</Select.Item>
                    {/each}
                  </Select.Content>
                </Select.Root>
              </Field.Field>
              <Field.Field class="sm:col-span-2">
                <Field.Label for="template-description">{m.description()}</Field.Label>
                <Textarea
                  id="template-description"
                  maxlength={500}
                  rows={2}
                  value={description.text}
                  aria-describedby="template-description-help"
                  onfocus={description.focus}
                  onblur={description.blur}
                  oninput={(event) => {
                    description.text = event.currentTarget.value;
                    autosave.patch({ description: description.text });
                  }}
                />
                <Field.Description id="template-description-help"
                  >{m.widget_admin_template_description_description()}</Field.Description
                >
              </Field.Field>
              <Field.Field orientation="horizontal" class="sm:col-span-2">
                <Field.Content>
                  <Field.Label for="template-default"
                    >{m.widget_admin_template_default()}</Field.Label
                  >
                  <Field.Description id="template-default-help"
                    >{m.widget_admin_template_default_description()}</Field.Description
                  >
                </Field.Content>
                <Switch
                  id="template-default"
                  aria-describedby="template-default-help"
                  checked={template.is_default}
                  onCheckedChange={(checked) => autosave.patch({ is_default: checked })}
                />
              </Field.Field>
            </Field.Group>
          </Card.Content>
        </Card.Root>

        <Card.Root>
          <Card.Header>
            <Card.Title><h2>{m.widget_admin_template_locks()}</h2></Card.Title>
            <Card.Description>{m.widget_admin_template_locks_description()}</Card.Description>
          </Card.Header>
          <Card.Content>
            <Field.Group class="grid gap-4">
              {#each LOCK_GROUPS as group (group)}
                <Field.Field orientation="horizontal">
                  <Field.Content>
                    <Field.Label for={`template-lock-${group}`}
                      >{lockLabels[group].label}</Field.Label
                    >
                    <Field.Description id={`template-lock-${group}-help`}
                      >{lockLabels[group].description}</Field.Description
                    >
                    {#if group === "legal_texts" && !hasSubtitle && !template.locked_groups.includes(group)}
                      <Field.Description
                        id="template-lock-legal-texts-blocked"
                        class="text-warning-stronger"
                        >{m.widget_admin_template_lock_needs_subtitle()}</Field.Description
                      >
                    {/if}
                  </Field.Content>
                  <Switch
                    id={`template-lock-${group}`}
                    checked={template.locked_groups.includes(group)}
                    disabled={group === "legal_texts" &&
                      !hasSubtitle &&
                      !template.locked_groups.includes(group)}
                    aria-describedby={group === "legal_texts" && !hasSubtitle
                      ? `template-lock-${group}-help template-lock-legal-texts-blocked`
                      : `template-lock-${group}-help`}
                    onCheckedChange={(checked) => setLock(group, checked)}
                  />
                </Field.Field>
              {/each}
            </Field.Group>
          </Card.Content>
        </Card.Root>

        <Tabs.Root value="content" class="gap-6">
          <Tabs.List
            class="h-auto w-full flex-wrap gap-1 p-1 sm:w-auto"
            aria-label={m.widget_admin_template_details()}
          >
            <Tabs.Trigger value="content" class="h-9 px-3">
              <FileText aria-hidden="true" />
              {m.widget_admin_tab_content()}
            </Tabs.Trigger>
            <Tabs.Trigger value="appearance" class="h-9 px-3">
              <Palette aria-hidden="true" />
              {m.widget_admin_tab_appearance()}
            </Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="content">
            <Card.Root>
              <Card.Header>
                <Card.Title><h2>{m.widget_admin_texts()}</h2></Card.Title>
                <Card.Description>{m.widget_admin_template_texts_description()}</Card.Description>
              </Card.Header>
              <Card.Content>
                <WidgetTextsFields
                  texts={template.texts}
                  showSuggestions={false}
                  idPrefix="template"
                  errors={textErrors}
                  subtitleRequired={template.locked_groups.includes("legal_texts")
                    ? m.widget_admin_blocker_legal_texts_lock_subtitle()
                    : undefined}
                  onChange={(change) => autosave.patch({ texts: { ...template.texts, ...change } })}
                />
              </Card.Content>
            </Card.Root>
          </Tabs.Content>
          <Tabs.Content value="appearance">
            <Card.Root>
              <Card.Header>
                <Card.Title><h2>{m.widget_admin_appearance()}</h2></Card.Title>
                <Card.Description>{m.widget_admin_appearance_description()}</Card.Description>
              </Card.Header>
              <Card.Content>
                <WidgetThemeFields
                  theme={template.theme}
                  idPrefix="template"
                  onChange={(change) => autosave.patch({ theme: { ...template.theme, ...change } })}
                />
              </Card.Content>
            </Card.Root>
          </Tabs.Content>
        </Tabs.Root>
      </div>
      <aside class="min-w-0 self-start xl:sticky xl:top-4">
        <WidgetMockPreview name={template.name} texts={template.texts} theme={template.theme} />
      </aside>
    </div>
  </Page.Main>
</Page.Root>

<AlertDialog.Root bind:open={confirmPublish}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {template.linked_widgets === 1
          ? m.widget_admin_template_publish_confirm_title_one()
          : m.widget_admin_template_publish_confirm_title({
              count: String(template.linked_widgets)
            })}
      </AlertDialog.Title>
      <AlertDialog.Description>
        {m.widget_admin_template_publish_confirm_description()}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <ul
      class="flex list-disc flex-col gap-1 pl-5 text-sm"
      aria-label={m.widget_admin_template_publish_changes_label()}
    >
      {#if summary.written.length > 0}
        <li>{m.widget_admin_template_publish_writes({ parts: groupNames(summary.written) })}</li>
      {/if}
      {#if summary.newlyLocked.length > 0}
        <li>
          {m.widget_admin_template_publish_new_locks({ parts: groupNames(summary.newlyLocked) })}
        </li>
      {/if}
      {#if summary.released.length > 0}
        <li>
          {m.widget_admin_template_publish_released_locks({ parts: groupNames(summary.released) })}
        </li>
      {/if}
      {#if summary.changedUnlocked.length > 0}
        <li>
          {m.widget_admin_template_publish_unlocked_changes({
            parts: groupNames(summary.changedUnlocked)
          })}
        </li>
      {/if}
      {#if changesNothing}
        <li>{m.widget_admin_template_publish_no_widget_changes()}</li>
      {/if}
    </ul>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={publish.isLoading}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        disabled={publish.isLoading}
        onclick={(event) => {
          event.preventDefault();
          void publish();
        }}>{m.widget_admin_template_publish()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
