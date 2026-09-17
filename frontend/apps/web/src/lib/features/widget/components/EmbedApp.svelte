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
  import { DEFAULT_PRIMARY_COLOR, isHexColor, readableOn } from "../contrast";
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
  initChatService({
    eneo: client as unknown as Eneo,
    chatPartner: widgetChatPartner(initial.config),
    initialConversation: null,
    initialHistory: { items: [], count: 0, total_count: 0, next_cursor: null }
  });

  // A widget pinned to light or dark stays that way; "auto" follows the host
  // page (its `scheme` query parameter first, later `theme` messages) and
  // finally the visitor's system setting. The scheme is set on this document
  // only: the app's theme store would read and write the signed-in user's
  // preference in this origin's storage, which a visitor page must not touch.
  const pinnedScheme = initial.config.theme.color_scheme ?? "auto";

  function applyScheme(scheme: Scheme) {
    const effective = pinnedScheme === "auto" ? scheme : pinnedScheme;
    document.documentElement.dataset.theme = effective === "auto" ? "system" : effective;
  }

  onMount(() => applyScheme(initial.hostScheme ?? "auto"));

  // The widget's own colours as CSS variables; text colours are derived so the
  // combination always reads (WCAG 1.4.3 / 1.4.11).
  const accent = $derived(
    isHexColor(config.theme.primary_color ?? "")
      ? config.theme.primary_color!
      : DEFAULT_PRIMARY_COLOR
  );
  const header = $derived(
    config.theme.header_color && isHexColor(config.theme.header_color)
      ? config.theme.header_color
      : null
  );
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
