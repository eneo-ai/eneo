<!--
  The real embed page in an iframe, driven by a preview token so drafts work
  too. Reloads after every saved change; re-mints the token when a change
  bumps the widget's token generation and shortly before it expires.
-->
<script lang="ts">
  import type { Eneo, Widget } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { previewEmbedPath } from "../preview";
  import { watchAppScheme } from "./appScheme.svelte";

  type Scheme = "auto" | "light" | "dark";

  type Props = {
    widget: Widget;
    eneo: Eneo;
    /** 3 where the preview sits inside another section. */
    headingLevel?: 2 | 3;
    title?: string;
  };

  let { widget, eneo, headingLevel = 2, title }: Props = $props();

  let token = $state<string | null>(null);
  let tokenGeneration = $state<number | null>(null);
  let failed = $state(false);
  let scheme = $state<Scheme>("auto");
  let mobile = $state(false);
  // "Auto" follows what the admin sees in Eneo right now, also after a theme switch.
  const appScheme = watchAppScheme();

  const lang = $derived(widget.language === "en" ? "en" : "sv");
  // A widget pinned to light or dark previews that way whatever the toggle says.
  const pinnedScheme = $derived(
    widget.theme.color_scheme === "light" || widget.theme.color_scheme === "dark"
      ? widget.theme.color_scheme
      : null
  );

  // setTimeout fires at once for longer delays.
  const MAX_TIMEOUT = 2_147_483_647;
  let renewal: ReturnType<typeof setTimeout> | undefined;
  let destroyed = false;

  async function mint(): Promise<void> {
    // A token is minted for the generation current when it was requested. A
    // rules save can advance the generation (and start another mint) before
    // this one answers; a late answer is then stale and the backend would
    // reject it, so it must neither replace the current token nor be
    // recorded as covering the new generation.
    const requested = { id: widget.id, generation: widget.token_generation };
    const current = () =>
      requested.id === widget.id && requested.generation === widget.token_generation;
    clearTimeout(renewal);
    failed = false;
    try {
      const minted = await eneo.widgets.previewToken({ id: requested.id });
      if (!current()) return;
      token = minted.token;
      tokenGeneration = requested.generation;
      // The framed chat sends this token with every request, so it is renewed
      // a minute before it expires rather than left to die in the frame.
      clearTimeout(renewal);
      if (destroyed) return;
      const renewIn = Math.max(minted.expires_in - 60, minted.expires_in / 2);
      renewal = setTimeout(
        () => {
          if (widget.status !== "archived") void mint();
        },
        Math.min(renewIn * 1000, MAX_TIMEOUT)
      );
    } catch (error) {
      if (!current()) return;
      failed = true;
      toastError(error, m.widget_admin_preview_failed());
    }
  }

  // One automatic attempt per generation: every edit hands this effect a new
  // widget, and a failed mint is retried with the reload button, not per
  // keystroke.
  let attempted: number | null = null;
  $effect(() => {
    if (widget.status === "archived") return;
    const generation = widget.token_generation;
    if (tokenGeneration === generation || attempted === generation) return;
    attempted = generation;
    void mint();
  });
  $effect(() => () => {
    destroyed = true;
    clearTimeout(renewal);
  });

  const src = $derived.by(() => {
    if (!token) return null;
    const path = previewEmbedPath(widget.public_id, token, lang);
    const effective = pinnedScheme ?? (scheme === "auto" ? appScheme.current : scheme);
    const query = `&scheme=${effective}`;
    // updated_at forces a reload after every saved change.
    return path.replace("#", `${query}&v=${encodeURIComponent(widget.updated_at)}#`);
  });

  const schemes: Array<{ value: Scheme; label: () => string }> = [
    { value: "auto", label: () => m.widget_admin_scheme_auto() },
    { value: "light", label: () => m.widget_admin_scheme_light() },
    { value: "dark", label: () => m.widget_admin_scheme_dark() }
  ];
</script>

<section
  aria-labelledby="widget-preview-title"
  class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
>
  <div class="flex flex-wrap items-center justify-between gap-2">
    <svelte:element
      this={`h${headingLevel}`}
      id="widget-preview-title"
      class="text-base font-semibold">{title ?? m.widget_admin_preview()}</svelte:element
    >
    <div class="flex flex-wrap items-center gap-2">
      <div role="group" aria-label={m.widget_admin_preview_scheme()} class="flex gap-1">
        {#each schemes as option (option.value)}
          <Button
            variant={scheme === option.value ? "default" : "outline"}
            aria-pressed={scheme === option.value}
            disabled={pinnedScheme !== null}
            onclick={() => (scheme = option.value)}>{option.label()}</Button
          >
        {/each}
      </div>
      <Button
        variant={mobile ? "default" : "outline"}
        aria-pressed={mobile}
        onclick={() => (mobile = !mobile)}>{m.widget_admin_preview_mobile()}</Button
      >
      <Button variant="outline" onclick={mint}>{m.widget_admin_preview_reload()}</Button>
    </div>
  </div>
  <p class="text-secondary text-sm">
    {pinnedScheme
      ? m.widget_admin_preview_scheme_pinned({
          scheme:
            pinnedScheme === "dark" ? m.widget_admin_scheme_dark() : m.widget_admin_scheme_light()
        })
      : m.widget_admin_preview_description()}
  </p>

  <div class="bg-secondary flex justify-center rounded-lg p-3">
    {#if failed}
      <p role="alert" class="text-negative-default py-10 text-sm">
        {m.widget_admin_preview_failed()}
      </p>
    {:else if src}
      <!-- Same origin as this page: a sandbox attribute would be no barrier here, so none is pretended. -->
      <iframe
        {src}
        title={m.widget_admin_preview_frame_title()}
        class="border-default bg-primary rounded-lg border shadow"
        style:width={mobile ? "375px" : "100%"}
        style:height="600px"
      ></iframe>
    {:else}
      <p class="text-secondary py-10 text-sm" aria-live="polite">{m.widget_preview_loading()}</p>
    {/if}
  </div>
</section>
