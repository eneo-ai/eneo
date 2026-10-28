<!--
  A static rendering of how a template's colours, logo and texts come
  together: launcher, header, welcome, a sample bubble and the composer.
  Templates have no widget behind them, so there is nothing live to frame;
  the real embed page is previewed on the widget page after the template has
  been applied.
-->
<script lang="ts">
  import type { WidgetPersona, WidgetTexts, WidgetTheme } from "@eneo/eneo-js";
  import { IconSendArrow } from "@eneo/icons/send-arrow";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import Moon from "@lucide/svelte/icons/moon";
  import Sun from "@lucide/svelte/icons/sun";
  import { untrack } from "svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { contrastRatio, readableOn, themeColors } from "../contrast";
  import { monogram } from "../persona";
  import { currentAppScheme } from "./appScheme";
  import { linkHost } from "../urls";
  import WidgetPersonaByline from "../components/WidgetPersonaByline.svelte";

  type Props = {
    name: string;
    texts: WidgetTexts;
    theme: WidgetTheme;
    persona?: WidgetPersona | null;
  };

  let { name, texts, theme, persona = null }: Props = $props();

  const eneo = getEneo();
  // What the embed page shows: the same byline, the same avatar rule.
  const personaPreview = $derived.by(() => {
    const name = persona?.name;
    if (!name) return null;
    return {
      name,
      avatarUrl: persona.avatar_icon_id ? eneo.icons.url({ id: persona.avatar_icon_id }) : null,
      monogram: monogram(name),
      inLauncher: !!persona.avatar_icon_id && (persona.avatar_in_launcher ?? false)
    };
  });

  // Previewed in the scheme the template pins, else what the admin sees in
  // Eneo; the toggle lets them check the other one.
  const pinned = $derived(
    theme.color_scheme === "light" || theme.color_scheme === "dark" ? theme.color_scheme : null
  );
  let scheme = $state<"light" | "dark">(untrack(() => pinned ?? currentAppScheme()));
  $effect(() => {
    if (pinned) scheme = pinned;
  });
  const dark = $derived(scheme === "dark");
  const colors = $derived(themeColors(theme, dark));
  const accent = $derived(colors.accent);
  const header = $derived(colors.header);
  const radius = $derived(`${theme.radius ?? 12}px`);
  const left = $derived(theme.position === "bottom-left");
  const avatarOnAccent = $derived(contrastRatio(readableOn(accent), accent) >= 4.5);
</script>

<section
  aria-labelledby="widget-mock-preview-title"
  class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
>
  <div class="flex flex-wrap items-center justify-between gap-2">
    <h2 id="widget-mock-preview-title" class="text-base font-semibold">
      {m.widget_admin_template_preview()}
    </h2>
    <div role="group" aria-label={m.widget_admin_preview_scheme()} class="flex gap-1">
      <Button
        variant={dark ? "outline" : "secondary"}
        size="sm"
        aria-pressed={!dark}
        onclick={() => (scheme = "light")}
      >
        <Sun aria-hidden="true" data-icon="inline-start" />
        {m.widget_admin_scheme_light()}
      </Button>
      <Button
        variant={dark ? "secondary" : "outline"}
        size="sm"
        aria-pressed={dark}
        onclick={() => (scheme = "dark")}
      >
        <Moon aria-hidden="true" data-icon="inline-start" />
        {m.widget_admin_scheme_dark()}
      </Button>
    </div>
  </div>
  <p class="text-secondary text-sm">{m.widget_admin_template_preview_description()}</p>

  <div
    class={["bg-secondary flex items-end gap-3 rounded-lg p-4", left && "flex-row-reverse"]}
    data-theme={scheme}
    role="img"
    aria-label={m.widget_admin_template_preview_alt({ name })}
  >
    <div
      class="bg-primary text-primary flex w-full max-w-sm flex-col overflow-hidden shadow"
      style:border-radius={radius}
    >
      <div
        class={["flex items-center gap-3 px-4 py-3", !header && "border-default border-b"]}
        style:background={header}
        style:color={header ? readableOn(header) : null}
      >
        {#if theme.logo_url}
          <img
            class="h-8 w-8 shrink-0 rounded-md object-contain"
            src={theme.logo_url}
            alt=""
            width="32"
            height="32"
          />
        {/if}
        <div class="min-w-0">
          <p class="truncate text-base font-semibold">{texts.title || name}</p>
          <p class={["text-xs", header ? "opacity-85" : "text-secondary"]}>
            {texts.subtitle}
          </p>
        </div>
      </div>
      <div
        class="flex flex-col gap-3 px-4 py-4"
        style:--widget-avatar-bg={avatarOnAccent ? accent : null}
        style:--widget-avatar-fg={avatarOnAccent ? readableOn(accent) : null}
      >
        {#if personaPreview}
          <WidgetPersonaByline persona={personaPreview} />
        {/if}
        {#if texts.welcome}
          <p class="text-sm whitespace-pre-wrap">{texts.welcome}</p>
        {/if}
        <div class="flex justify-end">
          <span
            class="max-w-[80%] px-3 py-2 text-sm"
            style:background={accent}
            style:color={readableOn(accent)}
            style:border-radius={radius}
            style:border-bottom-right-radius="4px"
          >
            {m.widget_admin_template_preview_sample_question()}
          </span>
        </div>
      </div>
      <div class="border-default flex flex-col gap-2 border-t px-4 py-3">
        <div
          class="border-default text-muted flex items-center justify-between border px-3 py-2 text-sm"
          style:border-radius={radius}
        >
          <span>{texts.placeholder || m.widget_input_placeholder()}</span>
          <span
            class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
            style:background={accent}
            style:color={readableOn(accent)}
            aria-hidden="true"
          >
            <IconSendArrow size="sm" />
          </span>
        </div>
        {#if texts.footer_text || texts.footer_link_url}
          <p class="text-secondary text-xs">
            {texts.footer_text}
            {#if texts.footer_link_url}
              <span class="underline underline-offset-2"
                >{texts.footer_link_label || linkHost(texts.footer_link_url)}</span
              >
            {/if}
          </p>
        {/if}
      </div>
    </div>
    {#if personaPreview?.inLauncher && personaPreview.avatarUrl}
      <!-- The avatar as the launcher: ringed in the accent, with the chat
           glyph as a badge so it still reads as a chat. -->
      <span class="relative inline-block h-14 w-14 shrink-0" aria-hidden="true">
        <img
          class="h-14 w-14 rounded-full object-cover shadow"
          style:border="2px solid {accent}"
          src={personaPreview.avatarUrl}
          alt=""
          width="56"
          height="56"
        />
        <span
          class="absolute -right-0.5 -bottom-0.5 inline-flex h-6 w-6 items-center justify-center rounded-full"
          style:background={accent}
          style:color={readableOn(accent)}
          style:border="2px solid var(--background-primary)"
        >
          <svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="currentColor"
            ><path
              d="M4 3h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"
            /></svg
          >
        </span>
      </span>
    {:else}
      <span
        class="inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-full shadow"
        style:background={accent}
        style:color={readableOn(accent)}
        aria-hidden="true"
      >
        <!-- Same glyph as the loader's launcher button. -->
        <svg viewBox="0 0 24 24" class="h-7 w-7" fill="currentColor"
          ><path
            d="M4 3h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"
          /></svg
        >
      </span>
    {/if}
  </div>
</section>
