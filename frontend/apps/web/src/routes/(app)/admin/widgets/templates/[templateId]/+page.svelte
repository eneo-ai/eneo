<!--
  Edit one widget template: the house style editors copy onto new widgets.
  Autosaved like the widget page; a static preview shows the result.
-->
<script lang="ts">
  import { beforeNavigate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { toastError } from "$lib/core/errors";
  import { WidgetTemplateAutosave } from "$lib/features/widget/admin/widgetAutosave.svelte";
  import WidgetMockPreview from "$lib/features/widget/admin/WidgetMockPreview.svelte";
  import WidgetTextsFields from "$lib/features/widget/admin/WidgetTextsFields.svelte";
  import WidgetThemeFields from "$lib/features/widget/admin/WidgetThemeFields.svelte";
  import { m } from "$lib/paraglide/messages";
  import { FileText, Palette } from "lucide-svelte";
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
          toastError(error, m.widget_admin_save_failed());
          throw error;
        }
      })
  );

  beforeNavigate(() => {
    void autosave.flush();
  });

  const template = $derived(autosave.widget);

  const statusLabel = $derived(
    autosave.status === "saving"
      ? m.widget_admin_saving()
      : autosave.status === "saved"
        ? m.widget_admin_saved()
        : autosave.status === "error"
          ? m.widget_admin_save_failed()
          : ""
  );

  const languageLabels = $derived({
    auto: m.widget_admin_language_auto(),
    sv: m.widget_admin_language_sv(),
    en: m.widget_admin_language_en()
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.widget_admin_templates()} – {template.name}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{ title: m.widget_admin_nav(), href: resolve("/admin/widgets") }}
      title={template.name}
      truncate
    ></Page.Title>
    <Page.Flex>
      <span class="text-secondary text-sm" aria-live="polite" aria-atomic="true">{statusLabel}</span
      >
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    <div
      class="mx-auto grid w-full max-w-[1400px] gap-6 p-4 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]"
    >
      <div class="flex min-w-0 flex-col gap-6">
        <Card.Root>
          <Card.Header>
            <Card.Title>{m.widget_admin_template_details()}</Card.Title>
            <Card.Description>{m.widget_admin_template_name_description()}</Card.Description>
          </Card.Header>
          <Card.Content>
            <Field.Group class="grid gap-6 sm:grid-cols-2">
              <Field.Field>
                <Field.Label for="template-name">{m.name()}</Field.Label>
                <Input
                  id="template-name"
                  maxlength={100}
                  value={template.name}
                  oninput={(event) => autosave.patch({ name: event.currentTarget.value })}
                />
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
                  value={template.description}
                  aria-describedby="template-description-help"
                  oninput={(event) => autosave.patch({ description: event.currentTarget.value })}
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
                  <Field.Description
                    >{m.widget_admin_template_default_description()}</Field.Description
                  >
                </Field.Content>
                <Switch
                  id="template-default"
                  checked={template.is_default}
                  onCheckedChange={(checked) => autosave.patch({ is_default: checked })}
                />
              </Field.Field>
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
                <Card.Title>{m.widget_admin_texts()}</Card.Title>
                <Card.Description>{m.widget_admin_template_texts_description()}</Card.Description>
              </Card.Header>
              <Card.Content>
                <WidgetTextsFields
                  texts={template.texts}
                  showSuggestions={false}
                  idPrefix="template"
                  onChange={(change) => autosave.patch({ texts: { ...template.texts, ...change } })}
                />
              </Card.Content>
            </Card.Root>
          </Tabs.Content>
          <Tabs.Content value="appearance">
            <Card.Root>
              <Card.Header>
                <Card.Title>{m.widget_admin_appearance()}</Card.Title>
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
