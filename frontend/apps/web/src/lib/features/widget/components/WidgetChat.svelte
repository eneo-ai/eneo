<!--
  The chat a visitor sees inside the widget iframe (or on the stand-alone
  page). Reuses ChatService for streaming and state; everything visible is
  widget-specific so the WCAG contract in the ADR is enforced here.
-->
<script lang="ts">
  import "altcha";
  import type { AltchaWidgetElement } from "altcha";
  import type { WidgetClient, WidgetPublicConfig } from "@eneo/eneo-js";
  import { EneoError } from "@eneo/eneo-js";
  import { onMount, tick, untrack } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { getChatService } from "$lib/features/chat/ChatService.svelte";
  import { IconThumb } from "@eneo/icons/thumb";
  import { IconPlus } from "@eneo/icons/plus";
  import { solveWithAltcha } from "../altcha";
  import { createEmbedBridge } from "../embedBridge";
  import { VisitorSession, isTokenRejected, isWidgetUnavailable } from "../visitorSession";
  import WidgetComposer from "./WidgetComposer.svelte";
  import WidgetMessage from "./WidgetMessage.svelte";
  import TypingIndicator from "$lib/features/chat/components/conversation/TypingIndicator.svelte";

  type Props = {
    config: WidgetPublicConfig;
    client: WidgetClient;
    hostOrigin: string | null;
    onSession: (session: VisitorSession) => void;
    /** The host page's colour scheme, forwarded by the loader. */
    onTheme?: (scheme: "light" | "dark" | "auto") => void;
    /** Admin preview of a draft widget: used as the visitor token, nothing is remembered. */
    previewToken?: string | null;
  };

  let { config, client, hostOrigin, onSession, onTheme, previewToken = null }: Props = $props();

  const chat = getChatService();

  let altchaElement = $state<AltchaWidgetElement | null>(null);
  let composer = $state<WidgetComposer | null>(null);
  let log = $state<HTMLDivElement | null>(null);

  let status = $state<"idle" | "verifying" | "sending">("idle");
  let announcement = $state("");
  let errorMessage = $state<string | null>(null);
  let unavailable = $state(false);
  let feedbackGiven = $state<Record<string, 1 | -1>>({});
  // Shown while the backend has not yet confirmed the question (first chunk).
  let pendingQuestion = $state<string | null>(null);

  // Props are fixed for the lifetime of the page; capture them once.
  const initial = untrack(() => ({ client, config, hostOrigin, onSession, onTheme, previewToken }));

  const session = new VisitorSession({
    client: initial.client,
    config: initial.config,
    fixedToken: initial.previewToken,
    solve: () => {
      status = "verifying";
      return solveWithAltcha(altchaElement).finally(() => {
        if (status === "verifying") status = "idle";
      });
    }
  });
  initial.onSession(session);

  const bridge = createEmbedBridge({
    hostOrigin: initial.hostOrigin,
    handlers: {
      onOpen: () => composer?.focus(),
      onTheme: (scheme) => initial.onTheme?.(scheme)
    }
  });

  const messages = $derived(chat.currentConversation.messages ?? []);
  // The service appends the message once the backend confirms it; until then
  // show the question and a typing indicator so the visitor sees progress.
  const showPending = $derived(
    pendingQuestion !== null && !messages.some((message) => message.question === pendingQuestion)
  );
  const busy = $derived(status !== "idle" || chat.askQuestion.isLoading);
  const disclosure = $derived(config.texts.ai_disclosure);

  onMount(() => {
    bridge.ready();
    // Restore the visitor's last conversation on this site, if any.
    if (session.sessionId && session.hasIdentity) {
      void restore(session.sessionId);
    }
    return () => bridge.destroy();
  });

  async function restore(sessionId: string) {
    try {
      await session.ensureToken();
      await chat.loadConversation({ id: sessionId });
    } catch (error) {
      // A gone session (retention, pause) is not an error worth showing.
      session.rememberSession(null);
      if (isWidgetUnavailable(error) && !isSessionError(error)) unavailable = true;
    }
  }

  function isSessionError(error: unknown): boolean {
    return (
      error instanceof EneoError &&
      typeof (error.response as { detail?: { code?: string } } | undefined)?.detail?.code ===
        "string" &&
      (error.response as { detail: { code: string } }).detail.code === "session_not_owned"
    );
  }

  function errorCode(error: unknown): string | null {
    if (!(error instanceof EneoError)) return null;
    const detail = (error.response as { detail?: { code?: string } } | undefined)?.detail;
    return typeof detail?.code === "string" ? detail.code : null;
  }

  function describe(error: unknown): string {
    switch (errorCode(error)) {
      case "rate_limited_visitor":
      case "rate_limited_ip":
      case "rate_limited_mint":
      case "rate_limited_challenge":
        return m.widget_error_rate_limited();
      case "budget_exhausted":
        return m.widget_error_budget();
      case "widget_not_active":
      case "rate_limit_unavailable":
        return m.widget_error_unavailable();
      case "challenge_invalid":
      case "challenge_expired":
      case "challenge_replayed":
      case "challenge_required":
        return m.widget_error_verification();
      default:
        return m.widget_error_generic();
    }
  }

  async function send(question: string, retried = false): Promise<void> {
    errorMessage = null;
    const wasNew = !chat.currentConversation.id;
    pendingQuestion = question;
    try {
      await session.ensureToken();
      status = "sending";
      await chat.askQuestion(question);
      const sessionId = chat.currentConversation.id;
      if (sessionId) {
        session.rememberSession(sessionId);
        if (wasNew) bridge.conversationStarted(sessionId);
      }
      announcement = m.widget_answer_complete();
    } catch (error) {
      if (isTokenRejected(error) && !retried) {
        // Stale after a pause/config change or simply expired: re-mint once.
        session.invalidate();
        return send(question, true);
      }
      if (errorCode(error) === "widget_not_active") unavailable = true;
      errorMessage = describe(error);
      announcement = errorMessage;
    } finally {
      status = "idle";
      pendingQuestion = null;
      await tick();
      log?.scrollTo({ top: log.scrollHeight, behavior: "smooth" });
    }
  }

  function startOver() {
    chat.newConversation();
    session.rememberSession(null);
    errorMessage = null;
    composer?.focus();
  }

  async function feedback(value: 1 | -1) {
    const sessionId = chat.currentConversation.id;
    if (!sessionId || feedbackGiven[sessionId]) return;
    try {
      await client.conversations.leaveFeedback({
        conversation: { id: sessionId },
        feedback: { value }
      });
      feedbackGiven = { ...feedbackGiven, [sessionId]: value };
      announcement = m.widget_feedback_thanks();
    } catch (error) {
      errorMessage = describe(error);
    }
  }
</script>

<div class="bg-primary text-primary flex h-full min-h-0 flex-col" data-widget-chat>
  <header class="border-default flex items-center justify-between gap-2 border-b px-4 py-3">
    <div class="min-w-0">
      <h1 class="truncate text-base font-semibold">{config.texts.title || config.name}</h1>
      <p class="text-secondary text-xs">{disclosure}</p>
    </div>
    <div class="flex shrink-0 items-center gap-1">
      {#if messages.length > 0}
        <button
          type="button"
          class="text-secondary hover:bg-secondary focus-visible:ring-default flex h-9 w-9 items-center justify-center rounded-full focus-visible:ring-2 focus-visible:outline-none"
          onclick={startOver}
          aria-label={m.widget_new_conversation()}
          title={m.widget_new_conversation()}
        >
          <IconPlus size="sm" />
        </button>
      {/if}
      {#if bridge.embedded}
        <button
          type="button"
          class="text-secondary hover:bg-secondary focus-visible:ring-default flex h-9 w-9 items-center justify-center rounded-full text-lg leading-none focus-visible:ring-2 focus-visible:outline-none"
          onclick={() => bridge.close()}
          aria-label={m.widget_close()}
          title={m.widget_close()}>×</button
        >
      {/if}
    </div>
  </header>

  <div class="min-h-0 flex-1 overflow-y-auto px-4 py-4" bind:this={log}>
    {#if unavailable}
      <p class="text-secondary text-center text-sm">{m.widget_not_available_body()}</p>
    {:else if messages.length === 0 && !showPending}
      {#if config.texts.welcome}
        <p class="text-primary text-base whitespace-pre-wrap">{config.texts.welcome}</p>
      {/if}
    {:else}
      <ol role="log" aria-label={m.widget_conversation_log()} class="flex flex-col gap-6">
        {#each messages as message, index (index)}
          <WidgetMessage
            {message}
            {index}
            isLast={index === messages.length - 1}
            isLoading={chat.askQuestion.isLoading}
          />
        {/each}
        {#if showPending && pendingQuestion !== null}
          <li class="flex flex-col gap-3">
            <div class="flex justify-end">
              <p
                class="bg-accent-dimmer text-primary max-w-[85%] rounded-2xl rounded-br-sm px-4 py-2 text-base whitespace-pre-wrap"
              >
                <span class="sr-only">{m.widget_you()}: </span>{pendingQuestion}
              </p>
            </div>
            <TypingIndicator />
          </li>
        {/if}
      </ol>
      {#if chat.currentConversation.id && !chat.askQuestion.isLoading}
        {@const given = feedbackGiven[chat.currentConversation.id]}
        <div
          class="mt-3 flex items-center gap-1"
          role="group"
          aria-label={m.widget_feedback_prompt()}
        >
          <button
            type="button"
            class={[
              "focus-visible:ring-default flex h-8 w-8 items-center justify-center rounded-full focus-visible:ring-2 focus-visible:outline-none",
              given === 1
                ? "bg-accent-dimmer text-accent-default"
                : "text-secondary hover:bg-secondary"
            ]}
            aria-label={m.widget_feedback_helpful()}
            aria-pressed={given === 1}
            disabled={given !== undefined}
            onclick={() => feedback(1)}
          >
            <IconThumb size="sm" />
          </button>
          <button
            type="button"
            class={[
              "focus-visible:ring-default flex h-8 w-8 items-center justify-center rounded-full focus-visible:ring-2 focus-visible:outline-none",
              given === -1
                ? "bg-accent-dimmer text-accent-default"
                : "text-secondary hover:bg-secondary"
            ]}
            aria-label={m.widget_feedback_unhelpful()}
            aria-pressed={given === -1}
            disabled={given !== undefined}
            onclick={() => feedback(-1)}
          >
            <IconThumb size="sm" class="rotate-180" />
          </button>
        </div>
      {/if}
    {/if}
  </div>

  <div class="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>

  <footer class="border-default flex flex-col gap-2 border-t px-4 py-3">
    {#if errorMessage}
      <p role="alert" class="bg-negative-dimmer text-negative-default rounded-lg px-3 py-2 text-sm">
        {errorMessage}
      </p>
    {/if}
    {#if status === "verifying"}
      <p class="text-secondary text-xs">{m.widget_verifying()}</p>
    {/if}
    <WidgetComposer
      bind:this={composer}
      placeholder={config.texts.placeholder || m.widget_input_placeholder()}
      maxLength={config.max_question_chars}
      disabled={unavailable}
      {busy}
      suggestions={config.texts.suggested_questions ?? []}
      showSuggestions={messages.length === 0}
      onSend={(question) => void send(question)}
      onEscape={() => bridge.close()}
    />
    {#if config.texts.personal_data_notice || config.texts.privacy_url}
      <p class="text-secondary text-xs">
        {config.texts.personal_data_notice}
        {#if config.texts.privacy_url}
          <!-- eslint-disable svelte/no-navigation-without-resolve -- external privacy policy URL from widget configuration -->
          <a
            class="underline underline-offset-2"
            href={config.texts.privacy_url}
            target="_blank"
            rel="noopener noreferrer">{m.widget_privacy_link()}</a
          >
        {/if}
      </p>
    {/if}
  </footer>

  {#if config.bot_protection === "altcha"}
    <!-- Invisible proof of work: solved on first send, never part of the accessible UI. -->
    <div hidden aria-hidden="true">
      <altcha-widget
        bind:this={altchaElement}
        challenge={client.challengeUrl}
        auto="off"
        display="invisible"
        workers="2"
        configuration={JSON.stringify({ hideFooter: true, hideLogo: true, workers: 2 })}
      ></altcha-widget>
    </div>
  {/if}
</div>
