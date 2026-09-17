<!--
  Edit one widget template: the house style editors copy onto new widgets.
  Autosaved like the widget page; a static preview shows the result.
-->
<script lang="ts">
  import { Input } from "@eneo/ui";
  import { beforeNavigate } from "$app/navigation";
  import { Page, Settings } from "$lib/components/layout";
  import { toastError } from "$lib/core/errors";
  import { inputClass, textareaClass } from "$lib/features/widget/admin/fieldStyles";
  import { WidgetTemplateAutosave } from "$lib/features/widget/admin/widgetAutosave.svelte";
  import WidgetMockPreview from "$lib/features/widget/admin/WidgetMockPreview.svelte";
  import WidgetTextsFields from "$lib/features/widget/admin/WidgetTextsFields.svelte";
  import WidgetThemeFields from "$lib/features/widget/admin/WidgetThemeFields.svelte";
  import { m } from "$lib/paraglide/messages";
  import { resolve } from "$app/paths";
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
    <div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
      <div class="min-w-0">
        <Settings.Page>
          <Settings.Group title={m.general()}>
            <Settings.Row
              title={m.name()}
              description={m.widget_admin_template_name_description()}
              let:aria
            >
              <input
                type="text"
                class={inputClass}
                maxlength="100"
                {...aria}
                value={template.name}
                oninput={(event) => autosave.patch({ name: event.currentTarget.value })}
              />
            </Settings.Row>
            <Settings.Row
              title={m.description()}
              description={m.widget_admin_template_description_description()}
              let:aria
            >
              <textarea
                class={textareaClass}
                maxlength="500"
                {...aria}
                value={template.description}
                oninput={(event) => autosave.patch({ description: event.currentTarget.value })}
              ></textarea>
            </Settings.Row>
            <Settings.Row
              title={m.widget_admin_language()}
              description={m.widget_admin_language_description()}
              let:aria
            >
              <select
                class={inputClass}
                {...aria}
                value={template.language}
                onchange={(event) =>
                  autosave.patch({
                    language: event.currentTarget.value as typeof template.language
                  })}
              >
                <option value="auto">{m.widget_admin_language_auto()}</option>
                <option value="sv">{m.widget_admin_language_sv()}</option>
                <option value="en">{m.widget_admin_language_en()}</option>
              </select>
            </Settings.Row>
            <Settings.Row
              title={m.widget_admin_template_default()}
              description={m.widget_admin_template_default_description()}
            >
              <div class="border-default flex h-14 items-center border-b">
                <Input.Switch
                  value={template.is_default}
                  disabled={template.is_default}
                  sideEffect={({ next }) => next && autosave.patch({ is_default: true })}
                >
                  {m.widget_admin_template_default()}
                </Input.Switch>
              </div>
            </Settings.Row>
          </Settings.Group>

          <Settings.Group title={m.widget_admin_texts()}>
            <WidgetTextsFields
              texts={template.texts}
              onChange={(change) => autosave.patch({ texts: { ...template.texts, ...change } })}
            />
          </Settings.Group>

          <Settings.Group title={m.widget_admin_appearance()}>
            <WidgetThemeFields
              theme={template.theme}
              onChange={(change) => autosave.patch({ theme: { ...template.theme, ...change } })}
            />
          </Settings.Group>
        </Settings.Page>
      </div>
      <aside class="min-w-0 self-start p-4 xl:sticky xl:top-4">
        <WidgetMockPreview name={template.name} texts={template.texts} theme={template.theme} />
      </aside>
    </div>
  </Page.Main>
</Page.Root>
