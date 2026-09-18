<!--
  "Test in Eneo": mounts the real loader script and an <eneo-widget> element on
  this very page, so the launcher, panel, focus handling and keyboard flow can
  be tried exactly as on a host site before the snippet goes anywhere.
-->
<script lang="ts">
  import type { Eneo, Widget } from "@eneo/eneo-js";
  import { Button } from "@eneo/ui";
  import { onDestroy } from "svelte";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { currentAppScheme } from "./appScheme";

  type Props = {
    widget: Widget;
    eneo: Eneo;
  };

  let { widget, eneo }: Props = $props();

  let element = $state<HTMLElement | null>(null);
  let loading = $state(false);

  const active = $derived(element !== null);

  function loadLoader(): Promise<void> {
    if (customElements.get("eneo-widget")) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/widget/v1/eneo.js";
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error("loader"));
      document.head.appendChild(script);
    });
  }

  async function start() {
    loading = true;
    try {
      const [{ token }] = await Promise.all([
        eneo.widgets.previewToken({ id: widget.id }),
        loadLoader()
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
  <div>
    {#if active}
      <Button variant="outlined" onclick={stop}>{m.widget_admin_live_test_stop()}</Button>
    {:else}
      <Button variant="primary-outlined" onclick={start} disabled={loading}
        >{m.widget_admin_live_test_start()}</Button
      >
    {/if}
  </div>
</section>
