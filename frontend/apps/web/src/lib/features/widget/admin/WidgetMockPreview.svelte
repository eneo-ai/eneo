<!--
  A static rendering of how a template's colours and texts come together:
  launcher, header, welcome, suggestions and the composer. Templates have no
  widget behind them, so there is nothing live to frame; the real embed page
  is previewed on the widget page after the template has been applied.
-->
<script lang="ts">
  import type { WidgetTexts, WidgetTheme } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import { DEFAULT_PRIMARY_COLOR, isHexColor } from "./contrast";

  type Props = {
    name: string;
    texts: WidgetTexts;
    theme: WidgetTheme;
  };

  let { name, texts, theme }: Props = $props();

  const accent = $derived(
    isHexColor(theme.primary_color ?? "") ? theme.primary_color! : DEFAULT_PRIMARY_COLOR
  );
  const radius = $derived(`${theme.radius ?? 12}px`);
  const dark = $derived(theme.color_scheme === "dark");
</script>

<section
  aria-labelledby="widget-mock-preview-title"
  class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
>
  <h2 id="widget-mock-preview-title" class="text-base font-semibold">
    {m.widget_admin_template_preview()}
  </h2>
  <p class="text-secondary text-sm">{m.widget_admin_template_preview_description()}</p>

  <div
    class="bg-secondary flex justify-end gap-3 rounded-lg p-4"
    data-theme={dark ? "dark" : "light"}
    role="img"
    aria-label={m.widget_admin_template_preview_alt({ name })}
  >
    <div
      class="bg-primary text-primary flex w-full max-w-sm flex-col overflow-hidden shadow"
      style:border-radius={radius}
      style:--widget-accent={accent}
    >
      <div class="border-default border-b px-4 py-3">
        <p class="text-base font-semibold">{texts.title || name}</p>
        <p class="text-secondary text-xs">{texts.ai_disclosure}</p>
      </div>
      <div class="flex flex-col gap-3 px-4 py-4">
        {#if texts.welcome}
          <p class="text-sm whitespace-pre-wrap">{texts.welcome}</p>
        {/if}
        <div class="flex justify-end">
          <span
            class="text-on-fill max-w-[80%] px-3 py-2 text-sm"
            style:background={accent}
            style:border-radius={radius}
          >
            {m.widget_admin_template_preview_sample_question()}
          </span>
        </div>
        {#if texts.suggested_questions?.length}
          <div class="flex flex-wrap gap-2">
            {#each texts.suggested_questions.slice(0, 3) as question (question)}
              <span class="border-default border px-3 py-1 text-xs" style:border-radius={radius}
                >{question}</span
              >
            {/each}
          </div>
        {/if}
      </div>
      <div class="border-default flex flex-col gap-2 border-t px-4 py-3">
        <div
          class="border-default text-muted flex items-center justify-between border px-3 py-2 text-sm"
          style:border-radius={radius}
        >
          <span>{texts.placeholder || m.widget_input_placeholder()}</span>
          <span
            class="inline-block h-6 w-6 rounded-full"
            style:background={accent}
            aria-hidden="true"
          ></span>
        </div>
        {#if texts.personal_data_notice}
          <p class="text-secondary text-xs">{texts.personal_data_notice}</p>
        {/if}
      </div>
    </div>
    <span
      class="mt-auto inline-block h-14 w-14 shrink-0 rounded-full shadow"
      style:background={accent}
      aria-hidden="true"
    ></span>
  </div>
</section>
