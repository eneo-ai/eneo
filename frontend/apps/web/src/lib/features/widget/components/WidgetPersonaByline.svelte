<!--
  Who is answering: the persona's avatar, name and an AI marker, above the
  welcome text and above every answer. The byline is the visible form of the
  "Assistant:" prefix screen readers got before, so it is read once ("Sigge,
  AI-assistent") and never twice. The avatar is decorative; the name beside it
  carries the meaning (WCAG 1.1.1). The AI marker is not a setting (AI Act
  article 50).
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { PersonaView } from "../persona";

  type Props = {
    persona: PersonaView;
  };

  let { persona }: Props = $props();

  // An avatar the browser cannot load (gone, blocked) falls back to the
  // monogram instead of a broken image.
  let imageFailed = $state(false);
  const showImage = $derived(persona.avatarUrl !== null && !imageFailed);
</script>

<p class="widget-byline mb-1 flex items-center gap-2">
  <span
    class="widget-avatar size-6 shrink-0 overflow-hidden rounded-full text-xs"
    aria-hidden="true"
  >
    {#if showImage}
      <img
        class="size-full object-cover"
        src={persona.avatarUrl}
        alt=""
        referrerpolicy="no-referrer"
        onerror={() => (imageFailed = true)}
      />
    {:else}
      {persona.monogram}
    {/if}
  </span>
  <span class="flex min-w-0 items-center gap-1.5">
    <span class="text-primary text-sm font-semibold break-words">{persona.name}</span>
    <span class="widget-ai-chip" title={m.widget_persona_ai_assistant()}>
      <span aria-hidden="true">{m.widget_persona_ai_chip()}</span>
      <span class="sr-only">{m.widget_persona_ai_assistant()}</span>
    </span>
  </span>
</p>

<style>
  .widget-avatar {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    /* Accent only when its text colour reaches 4.5:1 on it; EmbedApp decides. */
    background: var(--widget-avatar-bg, var(--background-secondary));
    color: var(--widget-avatar-fg, var(--text-primary));
    font-weight: 600;
    line-height: 1;
    /* A transparent upload still has an edge on either scheme (WCAG 1.4.11). */
    box-shadow: inset 0 0 0 1px var(--border-default);
  }
  /* Text and a border, never colour alone; sized in em so it zooms with the
     name. Small text on the log's faint ground, so it keeps the full text
     colour for 4.5:1 (WCAG 1.4.3). */
  .widget-ai-chip {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--border-stronger);
    border-radius: 999px;
    padding: 0 0.4em;
    min-height: 1.4em;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--text-primary);
    white-space: nowrap;
  }
</style>
