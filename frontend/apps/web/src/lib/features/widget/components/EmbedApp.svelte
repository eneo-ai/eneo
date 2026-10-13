<!--
  Boots the chat for one widget: the widget client, the ChatService and the
  theme. Rendered by the embed page once the configuration is known (from the
  server for active widgets, client-side with a preview token for drafts).
-->
<script lang="ts">
  import { browser } from "$app/environment";
  import { createWidgetClient, type Eneo, type WidgetPublicConfig } from "@eneo/eneo-js";
  import { onMount, untrack } from "svelte";
  import { initChatService } from "$lib/features/chat/ChatService.svelte";
  import type { VisitorSession } from "../visitorSession";
  import { readableOn, themeColors } from "../contrast";
  import { widgetChatPartner } from "../widgetPartner";
  import WidgetChat from "./WidgetChat.svelte";

  type Scheme = "light" | "dark" | "auto";

  type Props = {
    config: WidgetPublicConfig;
    publicId: string;
    baseUrl: string;
    hostOrigin: string | null;
    hostScheme: Scheme | null;
    previewToken?: string | null;
  };

  let { config, publicId, baseUrl, hostOrigin, hostScheme, previewToken = null }: Props = $props();

  let session: VisitorSession | null = null;

  // The embed page never navigates between widgets; its data is fixed.
  const initial = untrack(() => ({ config, publicId, baseUrl, hostOrigin, hostScheme }));

  const client = createWidgetClient({
    baseUrl: initial.baseUrl,
    publicId: initial.publicId,
    getToken: () => session?.token ?? null,
    fetch: browser ? fetch : undefined
  });

  // The widget client mirrors the `conversations` namespace the ChatService
  // drives; nothing else on the Eneo client is reachable from here.
  // A broken-off answer keeps what arrived and is reported by the chat's own
  // localized alert instead of an error block written into the answer.
  initChatService({
    eneo: client as unknown as Eneo,
    chatPartner: widgetChatPartner(initial.config),
    initialConversation: null,
    initialHistory: { items: [], count: 0, total_count: 0, next_cursor: null },
    inlineStreamErrors: false
  });

  // A widget pinned to light or dark stays that way; "auto" follows the host
  // page (its `scheme` query parameter first, later `theme` messages) and
  // finally the visitor's system setting. The scheme is set on this document
  // only: the app's theme store would read and write the signed-in user's
  // preference in this origin's storage, which a visitor page must not touch.
  const pinnedScheme = initial.config.theme.color_scheme ?? "auto";

  // Whether the panel is dark right now, so the widget's own colours can
  // switch with it. Starts from what the server rendered.
  let dark = $state(
    untrack(() => (pinnedScheme === "auto" ? initial.hostScheme : pinnedScheme) === "dark")
  );
  let systemQuery: MediaQueryList | null = null;

  function applyScheme(scheme: Scheme) {
    const effective = pinnedScheme === "auto" ? scheme : pinnedScheme;
    document.documentElement.dataset.theme = effective === "auto" ? "system" : effective;
    dark = effective === "auto" ? (systemQuery?.matches ?? false) : effective === "dark";
  }

  onMount(() => {
    systemQuery = matchMedia("(prefers-color-scheme: dark)");
    const followSystem = () => {
      if (document.documentElement.dataset.theme === "system") dark = systemQuery!.matches;
    };
    systemQuery.addEventListener("change", followSystem);
    applyScheme(initial.hostScheme ?? "auto");
    return () => systemQuery?.removeEventListener("change", followSystem);
  });

  // The widget's own colours as CSS variables, per scheme; text colours are
  // derived so the combination always reads (WCAG 1.4.3 / 1.4.11).
  const colors = $derived(themeColors(config.theme, dark));
  const accent = $derived(colors.accent);
  const header = $derived(colors.header);
</script>

<div
  class="bg-primary fixed inset-0 flex flex-col"
  style:--widget-accent={accent}
  style:--widget-on-accent={readableOn(accent)}
  style:--widget-header={header}
  style:--widget-on-header={header ? readableOn(header) : null}
  style:--widget-radius="{config.theme.radius ?? 12}px"
>
  <WidgetChat
    {config}
    {client}
    {hostOrigin}
    {previewToken}
    onSession={(created) => (session = created)}
    onTheme={applyScheme}
  />
</div>

<style>
  /* One focus indicator for every control in the widget, the dialogs
     included: the text colour reaches at least 3:1 against every surface
     the chat uses, in both schemes (WCAG 1.4.11, 2.4.7). Unlayered, so it
     wins over the utilities that switch outlines off. */
  :global(:focus-visible) {
    outline: 2px solid var(--text-primary);
    outline-offset: 2px;
  }
</style>
