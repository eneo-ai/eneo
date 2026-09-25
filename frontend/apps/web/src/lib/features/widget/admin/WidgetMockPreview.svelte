<!--
  A static rendering of how a template's colours, logo and texts come
  together: launcher, header, welcome, a sample bubble and the composer.
  Templates have no widget behind them, so there is nothing live to frame;
  the real embed page is previewed on the widget page after the template has
  been applied.
-->
<script lang="ts">
  import type { WidgetTexts, WidgetTheme } from "@eneo/eneo-js";
  import { IconEneo } from "@eneo/icons/eneo";
  import { IconSendArrow } from "@eneo/icons/send-arrow";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Moon, Sun } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { readableOn, themeColors } from "../contrast";
  import { currentAppScheme } from "./appScheme";
  import { linkHost } from "../urls";

  type Props = {
    name: string;
    texts: WidgetTexts;
    theme: WidgetTheme;
    /** Leave out the card, heading and template note, e.g. inside a section that has its own. */
    framed?: boolean;
    /** What the picture shows, for screen readers; defaults to the template wording. */
    alt?: string;
  };

  let { name, texts, theme, framed = true, alt }: Props = $props();

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
</script>

{#snippet schemeToggle()}
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
{/snippet}

{#snippet picture()}
  <div
    class={["bg-secondary flex items-end gap-3 rounded-lg p-4", left && "flex-row-reverse"]}
    data-theme={scheme}
    role="img"
    aria-label={alt ?? m.widget_admin_template_preview_alt({ name })}
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
        {:else}
          <span class="flex h-8 w-8 shrink-0 items-center justify-center" aria-hidden="true">
            <IconEneo size="md" class="text-brand-eneo" viewBox="0 -21 214 214" />
          </span>
        {/if}
        <div class="min-w-0">
          <p class="truncate text-base font-semibold">{texts.title || name}</p>
          <p class={["text-xs", header ? "opacity-85" : "text-secondary"]}>
            {texts.subtitle}
          </p>
        </div>
      </div>
      <div class="flex flex-col gap-3 px-4 py-4">
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
  </div>
{/snippet}

{#if framed}
  <section
    aria-labelledby="widget-mock-preview-title"
    class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
  >
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h2 id="widget-mock-preview-title" class="text-base font-semibold">
        {m.widget_admin_template_preview()}
      </h2>
      {@render schemeToggle()}
    </div>
    <p class="text-secondary text-sm">{m.widget_admin_template_preview_description()}</p>
    {@render picture()}
  </section>
{:else}
  <div class="flex flex-col gap-3">
    {@render schemeToggle()}
    {@render picture()}
  </div>
{/if}
