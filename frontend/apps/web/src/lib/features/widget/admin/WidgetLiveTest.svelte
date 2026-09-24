<!--
  "Test in Eneo": mounts the real loader script and an <eneo-widget> element on
  this very page, so the launcher, panel, focus handling and keyboard flow can
  be tried exactly as on a host site before the snippet goes anywhere.
-->
<script lang="ts">
  import type { Eneo, Widget } from "@eneo/eneo-js";
  import { Button } from "@eneo/ui";
  import { onDestroy } from "svelte";
  import { page } from "$app/state";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { currentAppScheme } from "./appScheme";
  import { loaderUrl, type LoaderRelease } from "./snippet";

  type Props = {
    widget: Widget;
    eneo: Eneo;
  };

  let { widget, eneo }: Props = $props();

  let element = $state<HTMLElement | null>(null);
  let loading = $state(false);

  const active = $derived(element !== null);
  // The loader build the widget page loaded; null when this installation has none.
  const release = $derived((page.data?.release ?? null) as LoaderRelease | null);

  function loadLoader(channel: string): Promise<void> {
    if (customElements.get("eneo-widget")) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = loaderUrl(page.url.origin, channel);
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error("loader"));
      document.head.appendChild(script);
    });
  }

  async function start() {
    if (!release) return;
    loading = true;
    try {
      const [{ token }] = await Promise.all([
        eneo.widgets.previewToken({ id: widget.id }),
        loadLoader(release.channel)
      ]);
      const mounted = document.createElement("eneo-widget");
      mounted.setAttribute("widget-id", widget.public_id);
      mounted.setAttribute("preview", token);
      mounted.setAttribute("position", widget.theme.position ?? "bottom-right");
      // Follow the admin's current Eneo theme unless the widget pins a scheme.
      const pinned = widget.theme.color_scheme;
      mounted.setAttribute(
        "color-scheme",
        pinned === "light" || pinned === "dark" ? pinned : currentAppScheme()
      );
      if (widget.language && widget.language !== "auto") {
        mounted.setAttribute("lang", widget.language);
      }
      // The launcher takes the widget's colours from the embed page itself.
      mounted.style.setProperty("--eneo-widget-radius", `${widget.theme.radius ?? 12}px`);
      document.body.appendChild(mounted);
      element = mounted;
      (mounted as HTMLElement & { openPanel?: () => void }).openPanel?.();
    } catch (error) {
      toastError(error, m.widget_admin_live_test_failed());
    } finally {
      loading = false;
    }
  }

  function stop() {
    element?.remove();
    element = null;
  }

  onDestroy(stop);
</script>

<section
  aria-labelledby="widget-live-test-title"
  class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
>
  <h2 id="widget-live-test-title" class="text-base font-semibold">{m.widget_admin_live_test()}</h2>
  <p class="text-secondary text-sm">{m.widget_admin_live_test_description()}</p>
  {#if !release}
    <p class="bg-warning-dimmer text-warning-stronger rounded-lg px-3 py-2 text-sm">
      {m.widget_admin_snippet_not_built()}
    </p>
  {/if}
  <div>
    {#if active}
      <Button variant="outlined" onclick={stop}>{m.widget_admin_live_test_stop()}</Button>
    {:else}
      <Button variant="primary-outlined" onclick={start} disabled={loading || !release}
        >{m.widget_admin_live_test_start()}</Button
      >
    {/if}
  </div>
</section>
