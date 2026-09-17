<script lang="ts">
  import { browser } from "$app/environment";
  import { createWidgetClient, type Eneo } from "@eneo/eneo-js";
  import { onMount, untrack } from "svelte";
  import { initChatService } from "$lib/features/chat/ChatService.svelte";
  import { getThemeStore } from "$lib/core/theme";
  import WidgetChat from "$lib/features/widget/components/WidgetChat.svelte";
  import type { VisitorSession } from "$lib/features/widget/visitorSession";
  import { widgetChatPartner } from "$lib/features/widget/widgetPartner";

  let { data } = $props();

  let session: VisitorSession | null = null;

  // The embed page never navigates between widgets; its data is fixed.
  const page = untrack(() => data);

  const client = createWidgetClient({
    baseUrl: page.baseUrl,
    publicId: page.publicId,
    getToken: () => session?.token ?? null,
    fetch: browser ? fetch : undefined
  });

  // The widget client mirrors the `conversations` namespace the ChatService
  // drives; nothing else on the Eneo client is reachable from here.
  initChatService({
    eneo: client as unknown as Eneo,
    chatPartner: widgetChatPartner(page.config),
    initialConversation: null,
    initialHistory: { items: [], count: 0, total_count: 0, next_cursor: null }
  });

  const theme = getThemeStore();

  onMount(() => {
    const scheme = data.config.theme.color_scheme ?? "auto";
    theme.set(scheme === "auto" ? "system" : scheme);
  });
</script>

<svelte:head>
  <title>{data.config.texts.title || data.config.name}</title>
  <meta name="robots" content="noindex" />
</svelte:head>

<div
  class="bg-primary fixed inset-0 flex flex-col"
  style:--widget-accent={data.config.theme.primary_color}
  style:--widget-radius="{data.config.theme.radius}px"
>
  <WidgetChat
    config={data.config}
    {client}
    hostOrigin={data.hostOrigin}
    onSession={(created) => (session = created)}
  />
</div>
