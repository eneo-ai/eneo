<!--
  The "Webbwidget" page body. Status and lifecycle on top; then four tabs in
  the order an editor works: what the chat says (Innehåll), how it looks
  (Utseende), where and how much it may run (Regler) and getting it onto the
  site (Publicera). The live preview sits beside the first two tabs.
-->
<script lang="ts">
  import type { Assistant, Eneo, Widget, WidgetPolicy, WidgetTemplate } from "@eneo/eneo-js";
  import { beforeNavigate } from "$app/navigation";
  import { page } from "$app/state";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { toastWidgetError } from "./errors";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { ExternalLink, FileText, Palette, Rocket, SlidersHorizontal } from "lucide-svelte";
  import { untrack } from "svelte";
  import { blockerLabel } from "./blockers";
  import { getCapability } from "$lib/features/mcp/capabilities";
  import { urlTab } from "./tabState.svelte";
  import type { LoaderRelease } from "./snippet";
  import { isGroupLocked, lockedTextFields } from "./templateLocks";
  import { collapseWhitespace, TextDraft } from "./textDraft.svelte";
  import TemplatePicker from "./TemplatePicker.svelte";
  import { WidgetAutosave } from "./widgetAutosave.svelte";
  import WidgetLiveTest from "./WidgetLiveTest.svelte";
  import WidgetPreview from "./WidgetPreview.svelte";
  import WidgetRulesFields from "./WidgetRulesFields.svelte";
  import WidgetSnippet from "./WidgetSnippet.svelte";
  import WidgetStatusBar from "./WidgetStatusBar.svelte";
  import WidgetTextsFields from "./WidgetTextsFields.svelte";
  import WidgetThemeFields from "./WidgetThemeFields.svelte";
  import WidgetUsage from "./WidgetUsage.svelte";

  type Props = {
    widget: Widget;
    assistant: Assistant;
    eneo: Eneo;
    isAdmin: boolean;
    policy: WidgetPolicy | null;
    release: LoaderRelease | null;
    templates?: WidgetTemplate[];
  };

  let {
    widget,
    assistant,
    eneo,
    isAdmin,
    policy,
    release,
    templates: allTemplates = []
  }: Props = $props();
  // Widgets follow a template's published release, so drafts are not offered.
  const templates = $derived(allTemplates.filter((t) => t.published_at != null));

  const autosave = untrack(
    () =>
      new WidgetAutosave(widget, async (update) => {
        try {
          return await eneo.widgets.update({ widget: { id: widget.id }, update });
        } catch (error) {
          toastWidgetError(error, m.widget_admin_save_failed());
          throw error;
        }
      })
  );

  // Leaving saves what is pending. When saving has already failed the edits
  // would be lost for good, so the editor is asked before they are discarded.
  beforeNavigate((navigation) => {
    if (autosave.stranded && !confirm(m.widget_admin_unsaved_leave_confirm())) {
      navigation.cancel();
      return;
    }
    void autosave.flush();
  });

  const current = $derived(autosave.widget);

  // A blank name is never sent: the API would refuse it and hold every
  // later edit back with it.
  const name = new TextDraft(() => autosave.widget.name);
  const nameProblem = $derived(
    !collapseWhitespace(name.text) ? m.widget_admin_name_required() : autosave.refusals["name"]
  );
  const refusalsIn = (group: string) =>
    Object.fromEntries(
      Object.entries(autosave.refusals)
        .filter(([path]) => path.startsWith(`${group}.`))
        .map(([path, message]) => [path.slice(group.length + 1), message])
    );
  const textErrors = $derived(refusalsIn("texts"));
  // The theme fields check what they send, so a refusal here is rare and
  // shown once for the whole appearance.
  const appearanceErrors = $derived([
    ...new Set([autosave.refusals["theme"], ...Object.values(refusalsIn("theme"))].filter(Boolean))
  ]);
  const tab = urlTab(["content", "appearance", "rules", "publish"] as const, "content");

  // Pending edits are saved first so pause and archive never race the
  // autosave; a save that fails does not stop the kill switch.
  const lifecycle = (action: (params: { id: string }) => Promise<Widget>) => async () => {
    await autosave.flush();
    autosave.replace(await action({ id: widget.id }));
  };

  // Linking a template overwrites texts and appearance, so it asks first;
  // detaching hands every part back to the editor, so it asks too. Reapplying
  // is linking again: the release is copied whole, unlocked parts included.
  let templateChoice = $state("");
  let confirmTemplate = $state(false);
  let confirmReapply = $state(false);
  let confirmDetach = $state(false);
  let applying = $state(false);
  const chosenTemplate = $derived(templates.find((t) => t.id === templateChoice) ?? null);

  // The template the widget follows and what it freezes in this editor. The
  // server refuses locked changes too; the UI just stops them being attempted.
  const link = $derived(current.template ?? null);
  const lockedTexts = $derived(lockedTextFields(link));
  const languageLocked = $derived(isGroupLocked(link, "language"));
  const appearanceLocked = $derived(isGroupLocked(link, "appearance"));
  const lockHint = $derived(link ? m.widget_admin_template_locked_hint({ name: link.name }) : "");
  const groupLabels = $derived<Record<string, string>>({
    appearance: m.widget_admin_template_lock_appearance(),
    language: m.widget_admin_template_lock_language(),
    legal_texts: m.widget_admin_template_lock_legal_texts(),
    wording: m.widget_admin_template_lock_wording()
  });
  const lockedParts = $derived(
    (link?.locked_groups ?? []).map((group) => groupLabels[group] ?? group).join(", ")
  );

  // What linking copies from the template's release onto the widget.
  const RELEASE_GROUPS = ["texts", "theme", "language"];

  async function withTemplate(
    action: () => Promise<Widget>,
    failure: () => string,
    replaced: string[]
  ): Promise<boolean> {
    applying = true;
    try {
      await autosave.flush();
      if (autosave.hasPending) return false;
      const updated = await action();
      // Refused edits of the groups the release replaced are moot; any other
      // refused edit stays on screen, held with its reason.
      autosave.discardRefused(replaced);
      autosave.replace(updated);
      return true;
    } catch (error) {
      toastWidgetError(error, failure());
      return false;
    } finally {
      applying = false;
    }
  }

  async function linkTemplate(templateId: string): Promise<boolean> {
    return withTemplate(
      () =>
        eneo.widgets.linkTemplate({
          widget: { id: widget.id },
          templateId,
          revision: current.revision
        }),
      () => m.widget_admin_template_could_not_apply(),
      RELEASE_GROUPS
    );
  }

  async function applyChosenTemplate() {
    if (!chosenTemplate) return;
    if (await linkTemplate(chosenTemplate.id)) {
      confirmTemplate = false;
      templateChoice = "";
    }
  }

  async function reapplyTemplate() {
    if (!link) return;
    if (await linkTemplate(link.id)) confirmReapply = false;
  }

  async function detachTemplate() {
    const done = await withTemplate(
      () => eneo.widgets.detachTemplate({ widget: { id: widget.id }, revision: current.revision }),
      () => m.widget_admin_template_could_not_detach(),
      []
    );
    if (done) confirmDetach = false;
  }

  const languageLabels = $derived({
    auto: m.widget_admin_language_auto(),
    sv: m.widget_admin_language_sv(),
    en: m.widget_admin_language_en()
  });

  const blockers = $derived(current.activation_blockers ?? []);
  // What an active widget exposes besides knowledge, as the backend serves
  // visitors: the assistant's general MCP servers as configured, and web
  // search only through an external provider (VISITOR_CAPABILITY_PURPOSES in
  // assistant_service.py). Image generation never.
  const VISITOR_CAPABILITIES: ReadonlySet<string> = new Set(["web_search"]);
  const visitorServers = $derived(
    (assistant.mcp_servers ?? []).filter(
      (server) => server.purpose === "general" && server.is_enabled
    )
  );
  const visitorCapabilities = $derived(
    (assistant.enabled_capabilities ?? [])
      .filter((purpose) => VISITOR_CAPABILITIES.has(purpose))
      .map((purpose) => getCapability(purpose)?.label() ?? purpose)
  );
  const showPreview = $derived(tab.value === "content" || tab.value === "appearance");
</script>

<svelte:window
  onbeforeunload={(event) => {
    if (autosave.unsaved) event.preventDefault();
  }}
/>

<div class="flex flex-col gap-6">
  <WidgetStatusBar
    {autosave}
    {isAdmin}
    onReload={async () => autosave.reload(await eneo.widgets.get({ id: widget.id }))}
    onActivate={lifecycle(eneo.widgets.activate)}
    onPause={lifecycle(eneo.widgets.pause)}
    onArchive={lifecycle(eneo.widgets.archive)}
  />

  <Tabs.Root bind:value={tab.value} class="gap-6">
    <Tabs.List
      class="h-auto w-full flex-wrap gap-1 p-1 sm:w-auto"
      aria-label={m.widget_admin_title()}
    >
      <Tabs.Trigger value="content" class="h-9 px-3">
        <FileText aria-hidden="true" />
        {m.widget_admin_tab_content()}
      </Tabs.Trigger>
      <Tabs.Trigger value="appearance" class="h-9 px-3">
        <Palette aria-hidden="true" />
        {m.widget_admin_tab_appearance()}
      </Tabs.Trigger>
      <Tabs.Trigger value="rules" class="h-9 px-3">
        <SlidersHorizontal aria-hidden="true" />
        {m.widget_admin_tab_rules()}
      </Tabs.Trigger>
      <Tabs.Trigger value="publish" class="h-9 px-3">
        <Rocket aria-hidden="true" />
        {m.widget_admin_tab_publish()}
        {#if blockers.length > 0}
          <Badge variant="destructive" class="ml-1"
            ><span aria-hidden="true">{blockers.length}</span><span class="sr-only"
              >{blockers.length === 1
                ? m.widget_admin_tab_issues_one()
                : m.widget_admin_tab_issues({ count: String(blockers.length) })}</span
            ></Badge
          >
        {/if}
      </Tabs.Trigger>
    </Tabs.List>

    <div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
      <div class="flex min-w-0 flex-col gap-6">
        <Tabs.Content value="content" class="flex flex-col gap-6">
          <Card.Root>
            <Card.Header>
              <Card.Title><h2>{m.general()}</h2></Card.Title>
              <Card.Description>{m.widget_admin_content_description()}</Card.Description>
            </Card.Header>
            <Card.Content>
              <Field.Group class="grid gap-6 sm:grid-cols-2">
                <Field.Field data-invalid={nameProblem ? true : undefined}>
                  <Field.Label for="widget-name">{m.name()}</Field.Label>
                  <Input
                    id="widget-name"
                    maxlength={100}
                    required
                    value={name.text}
                    aria-invalid={!!nameProblem}
                    aria-describedby={nameProblem
                      ? "widget-name-help widget-name-error"
                      : "widget-name-help"}
                    onfocus={name.focus}
                    onblur={name.blur}
                    oninput={(event) => {
                      name.text = event.currentTarget.value;
                      if (collapseWhitespace(name.text)) autosave.patch({ name: name.text });
                    }}
                  />
                  <Field.Description id="widget-name-help"
                    >{m.widget_admin_name_description()}</Field.Description
                  >
                  {#if nameProblem}
                    <Field.Error id="widget-name-error">{nameProblem}</Field.Error>
                  {/if}
                </Field.Field>
                <Field.Field>
                  <Field.Label for="widget-language">{m.widget_admin_language()}</Field.Label>
                  <Select.Root
                    type="single"
                    value={current.language ?? "auto"}
                    disabled={languageLocked}
                    onValueChange={(value) =>
                      autosave.patch({ language: value as NonNullable<Widget["language"]> })}
                  >
                    <Select.Trigger
                      id="widget-language"
                      class="w-full"
                      aria-describedby={languageLocked
                        ? "widget-language-help widget-language-lock"
                        : "widget-language-help"}
                    >
                      <span data-slot="select-value"
                        >{languageLabels[current.language ?? "auto"]}</span
                      >
                    </Select.Trigger>
                    <Select.Content>
                      {#each Object.entries(languageLabels) as [value, label] (value)}
                        <Select.Item {value} {label}>{label}</Select.Item>
                      {/each}
                    </Select.Content>
                  </Select.Root>
                  <Field.Description id="widget-language-help"
                    >{m.widget_admin_language_description()}</Field.Description
                  >
                  {#if languageLocked}
                    <Field.Description id="widget-language-lock">{lockHint}</Field.Description>
                  {/if}
                </Field.Field>
                <Field.Field orientation="horizontal" class="sm:col-span-2">
                  <Field.Content>
                    <Field.Label for="widget-show-sources"
                      >{m.widget_admin_show_sources()}</Field.Label
                    >
                    <Field.Description id="widget-show-sources-help"
                      >{m.widget_admin_show_sources_description()}</Field.Description
                    >
                  </Field.Content>
                  <Switch
                    id="widget-show-sources"
                    aria-describedby="widget-show-sources-help"
                    checked={current.show_sources ?? true}
                    onCheckedChange={(checked) => autosave.patch({ show_sources: checked })}
                  />
                </Field.Field>
                <Field.Field orientation="horizontal" class="sm:col-span-2">
                  <Field.Content>
                    <Field.Label for="widget-show-tool-activity"
                      >{m.widget_admin_show_tool_activity()}</Field.Label
                    >
                    <Field.Description id="widget-show-tool-activity-help"
                      >{m.widget_admin_show_tool_activity_description()}</Field.Description
                    >
                  </Field.Content>
                  <Switch
                    id="widget-show-tool-activity"
                    aria-describedby="widget-show-tool-activity-help"
                    checked={current.show_tool_activity ?? true}
                    onCheckedChange={(checked) => autosave.patch({ show_tool_activity: checked })}
                  />
                </Field.Field>
              </Field.Group>
            </Card.Content>
          </Card.Root>

          <Card.Root>
            <Card.Header>
              <Card.Title><h2>{m.widget_admin_texts()}</h2></Card.Title>
              <Card.Description>{m.widget_admin_texts_description()}</Card.Description>
            </Card.Header>
            <Card.Content class="flex flex-col gap-4">
              {#if autosave.refusals["texts"]}
                <Field.Error>{autosave.refusals["texts"]}</Field.Error>
              {/if}
              <WidgetTextsFields
                texts={current.texts}
                lockedFields={lockedTexts}
                {lockHint}
                errors={textErrors}
                subtitleRequired={current.status === "active"
                  ? m.widget_admin_blocker_subtitle_empty()
                  : undefined}
                onChange={(change) => autosave.patch({ texts: { ...current.texts, ...change } })}
              />
            </Card.Content>
          </Card.Root>
        </Tabs.Content>

        <Tabs.Content value="appearance" class="flex flex-col gap-6">
          {#if link}
            <Card.Root>
              <Card.Header>
                <Card.Title
                  ><h2>{m.widget_admin_template_linked_title({ name: link.name })}</h2></Card.Title
                >
                <Card.Description>{m.widget_admin_template_linked_description()}</Card.Description>
              </Card.Header>
              <Card.Content class="flex flex-col gap-4">
                <p class="text-sm">
                  {lockedParts
                    ? m.widget_admin_template_locked_parts({ parts: lockedParts })
                    : m.widget_admin_template_linked_none()}
                </p>
                <div class="flex flex-wrap items-center gap-2">
                  {#if isAdmin}
                    <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed route segment -->
                    <Button
                      variant="link"
                      class="h-auto px-0"
                      href={localizeHref(`/admin/widgets/templates/${link.id}`)}
                    >
                      {m.widget_admin_template_open()}
                      <ExternalLink data-icon="inline-end" aria-hidden="true" />
                    </Button>
                    <!-- eslint-enable svelte/no-navigation-without-resolve -->
                  {/if}
                  {#if current.status !== "archived"}
                    <Button variant="outline" onclick={() => (confirmReapply = true)}>
                      {m.widget_admin_template_reapply()}
                    </Button>
                    <Button variant="outline" onclick={() => (confirmDetach = true)}>
                      {m.widget_admin_template_detach()}
                    </Button>
                  {/if}
                </div>
              </Card.Content>
            </Card.Root>
          {:else if templates.length > 0 && current.status !== "archived"}
            <Card.Root>
              <Card.Header>
                <Card.Title><h2>{m.widget_admin_template_pick_title()}</h2></Card.Title>
                <Card.Description>{m.widget_admin_template_apply_description()}</Card.Description>
              </Card.Header>
              <Card.Content class="flex flex-col gap-4">
                <TemplatePicker
                  {templates}
                  bind:value={templateChoice}
                  legend={m.widget_admin_template_pick_title()}
                  id="widget-apply-template"
                />
                <div>
                  <Button
                    variant="outline"
                    disabled={!chosenTemplate}
                    onclick={() => (confirmTemplate = true)}
                  >
                    {m.widget_admin_template_apply()}
                  </Button>
                </div>
              </Card.Content>
            </Card.Root>
          {/if}

          <Card.Root>
            <Card.Header>
              <Card.Title><h2>{m.widget_admin_appearance()}</h2></Card.Title>
              <Card.Description>{m.widget_admin_appearance_description()}</Card.Description>
            </Card.Header>
            <Card.Content class="flex flex-col gap-4">
              {#each appearanceErrors as message (message)}
                <Field.Error>{message}</Field.Error>
              {/each}
              <WidgetThemeFields
                theme={current.theme}
                locked={appearanceLocked}
                {lockHint}
                onChange={(change) => autosave.patch({ theme: { ...current.theme, ...change } })}
              />
            </Card.Content>
          </Card.Root>
        </Tabs.Content>

        <Tabs.Content value="rules">
          <WidgetRulesFields {autosave} {policy} />
        </Tabs.Content>

        <Tabs.Content value="publish" class="flex flex-col gap-6">
          <Card.Root>
            <Card.Header>
              <Card.Title><h2>{m.widget_admin_publish_checklist()}</h2></Card.Title>
              <Card.Description>
                {assistant.published
                  ? m.widget_admin_publish_checklist_description()
                  : m.widget_admin_assistant_unpublished_description()}
              </Card.Description>
            </Card.Header>
            <Card.Content>
              {#if blockers.length === 0}
                <p class="text-positive-default text-sm">
                  {current.status === "active"
                    ? m.widget_admin_publish_live()
                    : m.widget_admin_publish_ready()}
                </p>
              {:else}
                <ul class="list-disc pl-5 text-sm">
                  {#each blockers as blocker (blocker)}
                    <li>{blockerLabel(blocker)}</li>
                  {/each}
                </ul>
              {/if}
              <section aria-labelledby="widget-visitor-access" class="mt-6 flex flex-col gap-1">
                <h3 id="widget-visitor-access" class="text-sm font-medium">
                  {m.widget_admin_visitor_access()}
                </h3>
                <p class="text-secondary text-sm">{m.widget_admin_visitor_access_description()}</p>
                <ul class="mt-1 list-disc pl-5 text-sm">
                  <li>{m.widget_admin_visitor_access_knowledge()}</li>
                  {#each visitorServers as server (server.id)}
                    <li>{server.name}</li>
                  {/each}
                  {#each visitorCapabilities as capability (capability)}
                    <li>{m.widget_admin_visitor_access_capability({ name: capability })}</li>
                  {/each}
                  {#if visitorServers.length + visitorCapabilities.length > 0 && !(current.show_tool_activity ?? true)}
                    <li class="text-secondary">{m.widget_admin_visitor_access_hidden()}</li>
                  {/if}
                </ul>
                <p class="text-secondary text-sm">{m.widget_admin_visitor_access_never()}</p>
              </section>
            </Card.Content>
          </Card.Root>
          <WidgetSnippet widget={current} {release} origin={page.url.origin} />
          <WidgetLiveTest widget={current} {eneo} />
          <WidgetUsage widget={current} {eneo} />
        </Tabs.Content>
      </div>

      <!-- Kept mounted across tabs so switching back does not mint a new
           preview token and reload the frame. -->
      <aside class="min-w-0 self-start xl:sticky xl:top-4" hidden={!showPreview}>
        <WidgetPreview widget={current} {eneo} />
      </aside>
    </div>
  </Tabs.Root>
</div>

<AlertDialog.Root bind:open={confirmTemplate}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.widget_admin_template_apply_confirm_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.widget_admin_template_apply_confirm_description({ name: chosenTemplate?.name ?? "" })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={applying}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        disabled={applying}
        onclick={(event) => {
          event.preventDefault();
          void applyChosenTemplate();
        }}>{m.widget_admin_template_apply()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root bind:open={confirmReapply}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.widget_admin_template_reapply_confirm_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.widget_admin_template_reapply_confirm_description({ name: link?.name ?? "" })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={applying}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        disabled={applying}
        onclick={(event) => {
          event.preventDefault();
          void reapplyTemplate();
        }}>{m.widget_admin_template_reapply()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root bind:open={confirmDetach}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.widget_admin_template_detach_confirm_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.widget_admin_template_detach_confirm_description({ name: link?.name ?? "" })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={applying}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        disabled={applying}
        onclick={(event) => {
          event.preventDefault();
          void detachTemplate();
        }}>{m.widget_admin_template_detach()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
