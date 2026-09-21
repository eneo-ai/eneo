<!--
  The real embed page in an iframe, driven by a preview token so drafts work
  too. Reloads after every saved change; re-mints the token when a change
  bumps the widget's token generation.
-->
<script lang="ts">
  import type { Eneo, Widget } from "@eneo/eneo-js";
  import { Button } from "@eneo/ui";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { previewEmbedPath } from "../preview";
  import { watchAppScheme } from "./appScheme.svelte";

  type Scheme = "auto" | "light" | "dark";

  type Props = {
    widget: Widget;
    eneo: Eneo;
  };

  let { widget, eneo }: Props = $props();

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

  async function mint(): Promise<void> {
    failed = false;
    try {
      const minted = await eneo.widgets.previewToken({ id: widget.id });
      token = minted.token;
      tokenGeneration = widget.token_generation;
    } catch (error) {
      failed = true;
      toastError(error, m.widget_admin_preview_failed());
    }
  }

  $effect(() => {
    if (widget.status === "archived") return;
    if (tokenGeneration !== widget.token_generation) void mint();
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
    <h2 id="widget-preview-title" class="text-base font-semibold">{m.widget_admin_preview()}</h2>
    <div class="flex flex-wrap items-center gap-2">
      <div role="group" aria-label={m.widget_admin_preview_scheme()} class="flex gap-1">
        {#each schemes as option (option.value)}
          <Button
            variant={scheme === option.value ? "primary-outlined" : "outlined"}
            aria-pressed={scheme === option.value}
            disabled={pinnedScheme !== null}
            onclick={() => (scheme = option.value)}>{option.label()}</Button
          >
        {/each}
      </div>
      <Button
        variant={mobile ? "primary-outlined" : "outlined"}
        aria-pressed={mobile}
        onclick={() => (mobile = !mobile)}>{m.widget_admin_preview_mobile()}</Button
      >
      <Button variant="outlined" onclick={mint}>{m.widget_admin_preview_reload()}</Button>
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
