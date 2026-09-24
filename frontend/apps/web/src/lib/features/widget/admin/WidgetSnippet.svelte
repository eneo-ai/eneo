<!--
  What the web editor pastes into the site: the floating loader snippet by
  default, a pinned+SRI variant on request, and the stand-alone page URL.
-->
<script lang="ts">
  import type { Widget } from "@eneo/eneo-js";
  import { Button, Input } from "@eneo/ui";
  import { Button as LinkButton } from "$lib/components/ui/button/index.js";
  import { ExternalLink } from "lucide-svelte";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { docsUrl } from "$lib/core/docs";
  import {
    floatingSnippet,
    pinnedSnippet,
    standaloneUrl,
    type LoaderRelease,
    type SnippetOptions
  } from "./snippet";

  type Props = {
    widget: Widget;
    release: LoaderRelease | null;
    origin: string;
  };

  let { widget, release, origin }: Props = $props();

  let pinned = $state(false);
  let announcement = $state("");

  const options = $derived({
    origin,
    publicId: widget.public_id,
    language: widget.language,
    release
  } satisfies SnippetOptions);
  const snippet = $derived(pinned ? pinnedSnippet(options) : floatingSnippet(options));
  const standalone = $derived(standaloneUrl(options));

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      announcement = m.widget_admin_copied({ what });
      toast.success(announcement);
    } catch {
      toast.error(m.widget_admin_copy_failed());
    }
  }
</script>

<section
  aria-labelledby="widget-snippet-title"
  class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
>
  <h2 id="widget-snippet-title" class="text-base font-semibold">{m.widget_admin_snippet()}</h2>
  <p class="text-secondary text-sm">{m.widget_admin_snippet_description()}</p>
  <LinkButton
    href={docsUrl("guides/embed-widget", getLocale(), "for-the-website-team")}
    target="_blank"
    rel="noreferrer"
    variant="link"
    size="sm"
    class="h-auto w-fit px-0"
  >
    {m.widget_admin_snippet_guide()}
    <ExternalLink data-icon="inline-end" aria-hidden="true" />
  </LinkButton>

  {#if widget.status !== "active"}
    <p class="bg-warning-dimmer text-warning-stronger rounded-lg px-3 py-2 text-sm">
      {m.widget_admin_snippet_inactive()}
    </p>
  {/if}

  {#if snippet}
    <pre
      class="bg-secondary text-primary rounded-lg p-3 text-xs break-all whitespace-pre-wrap"
      aria-label={m.widget_admin_snippet()}><code>{snippet}</code></pre>
  {:else}
    <p class="bg-warning-dimmer text-warning-stronger rounded-lg px-3 py-2 text-sm">
      {m.widget_admin_snippet_not_built()}
    </p>
  {/if}
  <div class="flex flex-wrap items-center justify-between gap-2">
    <Input.Switch value={pinned} sideEffect={({ next }) => (pinned = next)} disabled={!release}>
      {m.widget_admin_snippet_pinned()}
    </Input.Switch>
    <Button
      variant="primary-outlined"
      disabled={!snippet}
      onclick={() => snippet && copy(snippet, m.widget_admin_snippet())}
      >{m.widget_admin_copy()}</Button
    >
  </div>
  {#if pinned}
    <p class="text-secondary text-sm">{m.widget_admin_snippet_pinned_help()}</p>
  {/if}

  <h3 class="mt-2 text-sm font-medium">{m.widget_admin_standalone()}</h3>
  <p class="text-secondary text-sm">{m.widget_admin_standalone_description()}</p>
  <div class="flex items-center gap-2">
    <input
      type="text"
      readonly
      class="border-default bg-secondary min-w-0 flex-1 rounded-lg border px-3 py-2 text-xs"
      aria-label={m.widget_admin_standalone()}
      value={standalone}
    />
    <Button variant="outlined" onclick={() => copy(standalone, m.widget_admin_standalone())}
      >{m.widget_admin_copy()}</Button
    >
  </div>
  <div class="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
</section>
