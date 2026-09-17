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
  import { getThemeStore } from "$lib/core/theme";
  import type { VisitorSession } from "../visitorSession";
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

  const theme = getThemeStore();

  // A widget pinned to light or dark stays that way; "auto" follows the host
  // page (its `scheme` query parameter first, later `theme` messages).
  const pinnedScheme = initial.config.theme.color_scheme ?? "auto";

  function applyScheme(scheme: Scheme) {
    const effective = pinnedScheme === "auto" ? scheme : pinnedScheme;
    theme.set(effective === "auto" ? "system" : effective);
  }

  onMount(() => applyScheme(initial.hostScheme ?? "auto"));
</script>

<div
  class="bg-primary fixed inset-0 flex flex-col"
  style:--widget-accent={config.theme.primary_color}
  style:--widget-radius="{config.theme.radius}px"
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
