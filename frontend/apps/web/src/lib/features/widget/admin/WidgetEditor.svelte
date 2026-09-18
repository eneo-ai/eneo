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
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { FileText, Palette, Rocket, SlidersHorizontal } from "lucide-svelte";
  import { untrack } from "svelte";
  import { blockerLabel } from "./blockers";
  import { urlTab } from "./tabState.svelte";
  import type { LoaderRelease } from "./snippet";
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

  let { widget, assistant, eneo, isAdmin, policy, release, templates = [] }: Props = $props();

  const autosave = untrack(
    () =>
      new WidgetAutosave(widget, async (update) => {
        try {
          return await eneo.widgets.update({ widget: { id: widget.id }, update });
        } catch (error) {
          toastError(error, m.widget_admin_save_failed());
          throw error;
        }
      })
  );

  beforeNavigate(() => {
    void autosave.flush();
  });

  const current = $derived(autosave.widget);
  const tab = urlTab(["content", "appearance", "rules", "publish"] as const, "content");

  const lifecycle = (action: (params: { id: string }) => Promise<Widget>) => async () => {
    autosave.replace(await action({ id: widget.id }));
  };

  // Applying a template overwrites texts and appearance, so it asks first.
  let templateChoice = $state("");
  let confirmTemplate = $state(false);
  let applying = $state(false);
  const chosenTemplate = $derived(templates.find((t) => t.id === templateChoice) ?? null);

  async function applyTemplate() {
    if (!chosenTemplate) return;
    applying = true;
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      autosave.replace(
        await eneo.widgets.applyTemplate({
          widget: { id: widget.id },
          templateId: chosenTemplate.id,
          revision: current.revision
        })
      );
      confirmTemplate = false;
      templateChoice = "";
    } catch (error) {
      toastError(error, m.widget_admin_template_could_not_apply());
    } finally {
      applying = false;
    }
  }

  const languageLabels = $derived({
    auto: m.widget_admin_language_auto(),
    sv: m.widget_admin_language_sv(),
    en: m.widget_admin_language_en()
  });

  const blockers = $derived(current.activation_blockers ?? []);
</script>

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
        {#if blockers.length > 0 && current.status !== "active"}
          <Badge variant="destructive" class="ml-1">{blockers.length}</Badge>
        {/if}
      </Tabs.Trigger>
    </Tabs.List>

    <div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
      <div class="flex min-w-0 flex-col gap-6">
        <Tabs.Content value="content" class="flex flex-col gap-6">
          <Card.Root>
            <Card.Header>
              <Card.Title>{m.general()}</Card.Title>
              <Card.Description>{m.widget_admin_content_description()}</Card.Description>
            </Card.Header>
            <Card.Content>
              <Field.Group class="grid gap-6 sm:grid-cols-2">
                <Field.Field>
                  <Field.Label for="widget-name">{m.name()}</Field.Label>
                  <Input
                    id="widget-name"
                    maxlength={100}
                    value={current.name}
                    aria-describedby="widget-name-help"
                    oninput={(event) => autosave.patch({ name: event.currentTarget.value })}
                  />
                  <Field.Description id="widget-name-help"
                    >{m.widget_admin_name_description()}</Field.Description
                  >
                </Field.Field>
                <Field.Field>
                  <Field.Label for="widget-language">{m.widget_admin_language()}</Field.Label>
                  <Select.Root
                    type="single"
                    value={current.language ?? "auto"}
                    onValueChange={(value) =>
                      autosave.patch({ language: value as NonNullable<Widget["language"]> })}
                  >
                    <Select.Trigger
                      id="widget-language"
                      class="w-full"
                      aria-describedby="widget-language-help"
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
                </Field.Field>
              </Field.Group>
            </Card.Content>
          </Card.Root>

          <Card.Root>
            <Card.Header>
              <Card.Title>{m.widget_admin_texts()}</Card.Title>
              <Card.Description>{m.widget_admin_texts_description()}</Card.Description>
            </Card.Header>
            <Card.Content>
              <WidgetTextsFields
                texts={current.texts}
                onChange={(change) => autosave.patch({ texts: { ...current.texts, ...change } })}
              />
            </Card.Content>
          </Card.Root>
        </Tabs.Content>

        <Tabs.Content value="appearance" class="flex flex-col gap-6">
          {#if templates.length > 0 && current.status !== "archived"}
            <Card.Root>
              <Card.Header>
                <Card.Title>{m.widget_admin_template_pick_title()}</Card.Title>
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
              <Card.Title>{m.widget_admin_appearance()}</Card.Title>
              <Card.Description>{m.widget_admin_appearance_description()}</Card.Description>
            </Card.Header>
            <Card.Content>
              <WidgetThemeFields
                theme={current.theme}
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
              <Card.Title>{m.widget_admin_publish_checklist()}</Card.Title>
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
            </Card.Content>
          </Card.Root>
          <WidgetSnippet widget={current} {release} origin={page.url.origin} />
          <WidgetLiveTest widget={current} {eneo} />
          <WidgetUsage widget={current} {eneo} />
        </Tabs.Content>
      </div>

      {#if tab.value === "content" || tab.value === "appearance"}
        <aside class="min-w-0 self-start xl:sticky xl:top-4">
          <WidgetPreview widget={current} {eneo} />
        </aside>
      {/if}
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
          void applyTemplate();
        }}>{m.widget_admin_template_apply()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
