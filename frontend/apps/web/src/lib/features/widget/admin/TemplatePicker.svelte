<!--
  Choose a template: a radio group of cards, each showing the template's
  colours as swatches, its name and description and whether it is the
  organisation's default. Swatches and language come from the published
  release, which is what a widget receives; the draft may be ahead of it.
  Optionally offers "no template".
-->
<script lang="ts">
  import type { WidgetTemplate } from "@eneo/eneo-js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { m } from "$lib/paraglide/messages";
  import { DEFAULT_PRIMARY_COLOR, isHexColor } from "../contrast";
  import { templateRelease } from "./templateLocks";

  type Props = {
    templates: WidgetTemplate[];
    value: string;
    includeNone?: boolean;
    legend: string;
    id?: string;
  };

  let {
    templates,
    value = $bindable(),
    includeNone = false,
    legend,
    id = "widget-template"
  }: Props = $props();

  const NONE = "";

  function accent(template: WidgetTemplate) {
    const colour = templateRelease(template).theme.primary_color ?? "";
    return isHexColor(colour) ? colour : DEFAULT_PRIMARY_COLOR;
  }
  function header(template: WidgetTemplate) {
    const colour = templateRelease(template).theme.header_color ?? "";
    return isHexColor(colour) ? colour : null;
  }
  function languageLabel(language: WidgetTemplate["language"]) {
    return language === "sv"
      ? m.widget_admin_language_sv()
      : language === "en"
        ? m.widget_admin_language_en()
        : m.widget_admin_language_auto();
  }
</script>

<Field.Set>
  <Field.Legend class="sr-only">{legend}</Field.Legend>
  <RadioGroup.Root bind:value class="grid gap-3 sm:grid-cols-2">
    {#if includeNone}
      <Field.Label
        for={`${id}-none`}
        class="border-default has-data-[state=checked]:border-accent-default has-data-[state=checked]:bg-accent-dimmer w-auto cursor-pointer items-start rounded-xl border p-4"
      >
        <RadioGroup.Item id={`${id}-none`} value={NONE} class="mt-0.5" />
        <span class="flex flex-col gap-1">
          <span class="font-medium">{m.widget_admin_template_none()}</span>
          <span class="text-secondary text-sm">{m.widget_admin_template_none_description()}</span>
        </span>
      </Field.Label>
    {/if}
    {#each templates as template (template.id)}
      <Field.Label
        for={`${id}-${template.id}`}
        class="border-default has-data-[state=checked]:border-accent-default has-data-[state=checked]:bg-accent-dimmer w-auto cursor-pointer items-start rounded-xl border p-4"
      >
        <RadioGroup.Item id={`${id}-${template.id}`} value={template.id} class="mt-0.5" />
        <span class="flex min-w-0 flex-1 flex-col gap-2">
          <span class="flex flex-wrap items-center gap-2 font-medium">
            {template.name}
            {#if template.is_default}
              <Badge variant="outline">{m.widget_admin_template_default()}</Badge>
            {/if}
          </span>
          {#if template.description}
            <span class="text-secondary text-sm">{template.description}</span>
          {/if}
          <span class="flex items-center gap-2" aria-hidden="true">
            <span
              class="border-default inline-block h-6 w-6 rounded-full border"
              style:background={accent(template)}
            ></span>
            {#if header(template)}
              <span
                class="border-default inline-block h-6 w-10 rounded-md border"
                style:background={header(template)}
              ></span>
            {/if}
            {#if templateRelease(template).theme.logo_url}
              <img
                class="h-6 w-6 rounded object-contain"
                src={templateRelease(template).theme.logo_url}
                alt=""
                width="24"
                height="24"
              />
            {/if}
            <span class="text-secondary text-xs"
              >{languageLabel(templateRelease(template).language)}</span
            >
          </span>
          <span class="sr-only">
            {m.widget_admin_template_swatch_alt({
              accent: accent(template),
              header: header(template) ?? m.widget_admin_header_color_none()
            })}
          </span>
        </span>
      </Field.Label>
    {/each}
  </RadioGroup.Root>
</Field.Set>
