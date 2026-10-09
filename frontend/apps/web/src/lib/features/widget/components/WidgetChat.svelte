<!--
  The chat a visitor sees inside the widget iframe (or on the stand-alone
  page). Reuses ChatService for streaming and state; everything visible is
  widget-specific so the WCAG contract in the ADR is enforced here.
-->
<script lang="ts">
  import "altcha";
  import type { AltchaWidgetElement } from "altcha";
  import type { WidgetClient, WidgetPublicConfig } from "@eneo/eneo-js";
  import { onMount, tick, untrack } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { getChatService } from "$lib/features/chat/ChatService.svelte";
  import { IconEneo } from "@eneo/icons/eneo";
  import { launcherColors } from "../contrast";
  import { isHttpUrl, linkHost } from "../urls";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Maximize2, MessageSquarePlus, Minimize2, X } from "@lucide/svelte";
  import { solveWithAltcha } from "../altcha";
  import { Announcer } from "../announcer.svelte";
  import { answerText } from "../answerText";
  import { createEmbedBridge, type PanelLayout } from "../embedBridge";
  import { VisitorSession, isTokenRejected, isWidgetUnavailable } from "../visitorSession";
  import {
    MAX_COOLDOWN_SECONDS,
    describeWidgetError,
    isSessionError,
    retryAfterSeconds,
    widgetErrorCode
  } from "../widgetErrors";
  import WidgetComposer from "./WidgetComposer.svelte";
  import WidgetFeedback from "./WidgetFeedback.svelte";
  import WidgetMessage from "./WidgetMessage.svelte";
  import WidgetQuestionBubble from "./WidgetQuestionBubble.svelte";
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
  let challengeReady = $state(untrack(() => config.bot_protection === "altcha"));
  let composer = $state<WidgetComposer | null>(null);
  let draft = $state("");
  // How the loader shows the panel; null until a loader that reports it says.
  let layout = $state<PanelLayout | null>(null);
  let title = $state<HTMLHeadingElement | null>(null);
  let chatRoot = $state<HTMLElement | null>(null);
  let log = $state<HTMLElement | null>(null);
  let newQuestionButton = $state<HTMLButtonElement | null>(null);
  let startOverButton = $state<HTMLButtonElement | null>(null);

  let status = $state<"idle" | "verifying" | "sending">("idle");
  let restoring = $state(false);
  const announcer = new Announcer();
  let errorMessage = $state<string | null>(null);
  let unavailable = $state(false);
  // A 429 with Retry-After: the composer stays closed until the window passes.
  let coolingDown = $state(false);
  let cooldownTimer: ReturnType<typeof setTimeout> | null = null;
  // Shown while the backend has not yet confirmed the question (first chunk).
  let pendingQuestion = $state<string | null>(null);
  // How many messages there were when it was sent; the same text asked again
  // must still show as pending, so the count tells when it has arrived.
  let pendingFrom = $state(0);
  // The conversation whose first answer is in. Its feedback stays mounted
  // through follow-up questions, so a vote is not lost to the next one.
  let rateableSession = $state<string | null>(null);

  // Props are fixed for the lifetime of the page; capture them once.
  const initial = untrack(() => ({ client, config, hostOrigin, onSession, onTheme, previewToken }));

  const session = new VisitorSession({
    client: initial.client,
    config: initial.config,
    fixedToken: initial.previewToken,
    solve: async () => {
      // Restore what was in progress (a send stays "sending" until it ends).
      const before = status;
      status = "verifying";
      challengeReady = true;
      await tick();
      return solveWithAltcha(altchaElement).finally(() => {
        if (status === "verifying") status = before;
      });
    }
  });
  initial.onSession(session);

  const bridge = createEmbedBridge({
    hostOrigin: initial.hostOrigin,
    handlers: {
      onOpen: () => {
        // A touch device should open the conversation before its keyboard.
        // The heading gives screen readers context without panning the iframe.
        if (matchMedia("(pointer: coarse)").matches) title?.focus({ preventScroll: true });
        else composer?.focus();
      },
      onTheme: (scheme) => initial.onTheme?.(scheme),
      onLayout: (next) => {
        const before = layout;
        layout = next;
        // The control's name follows the new state; a screen reader also
        // hears that the request took effect. The first layout is not news.
        if (before && before.expanded !== next.expanded) {
          announcer.announce(
            next.expanded ? m.widget_expanded_announced() : m.widget_collapsed_announced()
          );
        }
      }
    }
  });
  // Expand grows the panel over the host page on a wide screen; on a small
  // screen the loader already fills the viewport, so there is nothing to offer.
  const expanded = $derived(layout?.expanded ?? false);
  const canExpand = $derived(bridge.embedded && layout !== null && (!layout.full || expanded));

  const messages = $derived(chat.currentConversation.messages ?? []);
  // The service appends the message once the backend confirms it; until then
  // show the question and a typing indicator so the visitor sees progress.
  const showPending = $derived(pendingQuestion !== null && messages.length <= pendingFrom);
  const busy = $derived(restoring || status !== "idle" || chat.askQuestion.isLoading);
  const subtitle = $derived(config.texts.subtitle);
  // Retention 0: the backend deletes the session when the answer ends, so
  // there is nothing to continue, rate or restore. Each question stands alone.
  const singleTurn = $derived(config.single_turn);
  const answered = $derived(singleTurn && messages.length > 0 && !busy);

  onMount(() => {
    bridge.ready(
      launcherColors(initial.config.theme),
      initial.config.texts.title || initial.config.name
    );
    if (initial.config.single_turn) {
      session.rememberSession(null);
    } else if (session.sessionId && session.hasIdentity) {
      // Restore the visitor's last conversation on this site, if any.
      restoring = true;
      void restore(session.sessionId).finally(() => (restoring = false));
    }
    return () => {
      if (cooldownTimer) clearTimeout(cooldownTimer);
      announcer.clear();
      bridge.destroy();
    };
  });

  $effect(() => {
    // The composer closes once a single-turn answer is in; keep the keyboard
    // on the one action that remains instead of dropping focus on the body.
    if (answered) void tick().then(() => newQuestionButton?.focus());
  });

  async function restore(sessionId: string, retried = false): Promise<void> {
    try {
      await session.ensureToken();
      // ChatService toasts and swallows load errors for the signed-in app;
      // here a gone session must be forgotten, not announced.
      await chat.loadConversation({ id: sessionId }, { rethrow: true });
      rateableSession = chat.currentConversation.id;
    } catch (error) {
      if (isTokenRejected(error) && !retried) {
        // Stale after a pause or a settings change: a fresh token for the
        // same visitor still owns the conversation.
        session.invalidate();
        return restore(sessionId, true);
      }
      // A gone session (retention, a new visitor identity) is not worth showing.
      session.rememberSession(null);
      if (isWidgetUnavailable(error) && !isSessionError(error)) unavailable = true;
    }
  }

  function coolDown(seconds: number) {
    coolingDown = true;
    if (cooldownTimer) clearTimeout(cooldownTimer);
    cooldownTimer = setTimeout(() => {
      coolingDown = false;
      errorMessage = null;
    }, seconds * 1000);
  }

  // Escape closes the panel from anywhere inside it, not only the textarea;
  // the confirm dialog handles its own Escape first and marks it as used.
  function onWindowKeydown(event: KeyboardEvent) {
    if (event.key !== "Escape" || event.defaultPrevented || confirmStartOver) return;
    if (!bridge.embedded) return;
    event.preventDefault();
    bridge.close();
  }

  async function send(question: string): Promise<void> {
    // One request at a time. The guard is synchronous, so a second click while
    // the token is minted or before the first chunk never starts another ask.
    if (restoring || status !== "idle" || chat.askQuestion.isLoading) return;
    status = "sending";
    errorMessage = null;
    pendingQuestion = question;
    pendingFrom = messages.length;
    // The typing dots are silent; this tells a screen reader the question went off.
    announcer.announce(m.assistant_is_typing());
    try {
      await ask(question, false);
    } finally {
      status = "idle";
      pendingQuestion = null;
      await tick();
      scrollToEnd();
    }
  }

  /** The conversation scrolls, or on a short panel the whole chat does. */
  function scrollToEnd() {
    const behavior = matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    for (const scroller of [log, chatRoot]) {
      scroller?.scrollTo({ top: scroller.scrollHeight, behavior });
    }
  }

  /** The turn exists on the server: remember it and tell the host page one began. */
  function keepConversation(wasNew: boolean) {
    const sessionId = chat.currentConversation.id;
    if (!sessionId) return;
    if (!singleTurn) session.rememberSession(sessionId);
    // The host page only learns that a conversation began, never its id.
    if (wasNew) bridge.conversationStarted();
    rateableSession = sessionId;
  }

  async function ask(question: string, retried: boolean): Promise<void> {
    const wasNew = !chat.currentConversation.id;
    const turns = chat.currentConversation.messages?.length ?? 0;
    try {
      await session.ensureToken();
      await chat.askQuestion(question);
      keepConversation(wasNew);
      // The finished answer is read once, as in any chat; the stream never
      // is (the log's own live region is off).
      const answer = answerText(chat.currentConversation.messages?.at(-1)?.answer ?? "");
      announcer.announce(
        answer ? `${m.widget_assistant()}: ${answer}` : m.widget_answer_complete()
      );
    } catch (error) {
      if ((chat.currentConversation.messages?.length ?? 0) > turns) {
        // The answer broke off after it began: what arrived stays, the alert
        // says it is incomplete and nothing announces it as done.
        announcer.clear();
        keepConversation(wasNew);
        errorMessage = m.widget_error_incomplete();
        return;
      }
      if (isTokenRejected(error) && !retried) {
        // Stale after a pause/config change or simply expired: re-mint once.
        session.invalidate();
        return ask(question, true);
      }
      // The alert below speaks for itself; a pending "typing" must not follow it.
      announcer.clear();
      // Nothing reached the server, so the question goes back into the field.
      void composer?.restore(question);
      const code = widgetErrorCode(error);
      if (code === "widget_not_active") unavailable = true;
      if (code === "session_not_owned") {
        // Deleted by retention, or owned by an identity this browser lost:
        // asking in it again can never succeed.
        chat.newConversation();
        session.rememberSession(null);
        errorMessage = m.widget_error_session_gone();
        return;
      }
      const wait = retryAfterSeconds(error);
      if (wait !== null && wait <= MAX_COOLDOWN_SECONDS) coolDown(wait);
      // The alert below announces the error itself; no second live message.
      errorMessage = describeWidgetError(error);
      // The conversation is full: the one way on is to start a new one.
      if (code === "session_turns_exceeded") void tick().then(() => startOverButton?.focus());
    }
  }

  // Starting over throws the visible conversation away, so it asks first.
  let confirmStartOver = $state(false);

  async function startOver() {
    confirmStartOver = false;
    chat.newConversation();
    session.rememberSession(null);
    errorMessage = null;
    await tick();
    composer?.focus();
  }

  /**
   * One vote or comment on the visible conversation. A vote often comes
   * minutes after the answer, so the token is refreshed like before a
   * question and re-minted once if it turned stale meanwhile.
   */
  async function submitFeedback(
    feedback: { value: 1 | -1; text?: string },
    retried = false
  ): Promise<string | null> {
    const sessionId = chat.currentConversation.id;
    if (!sessionId) return m.widget_error_generic();
    // Feedback owns the next error location, just as sending a question
    // clears an older feedback error. Never keep two attempts' alerts.
    errorMessage = null;
    try {
      await session.ensureToken();
      await client.conversations.leaveFeedback({ conversation: { id: sessionId }, feedback });
      return null;
    } catch (error) {
      if (isTokenRejected(error) && !retried) {
        session.invalidate();
        return submitFeedback(feedback, true);
      }
      // The feedback component shows this where the visitor is looking.
      return describeWidgetError(error);
    }
  }
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div
  class="widget-chat bg-primary text-primary flex h-full min-h-0 flex-col"
  data-widget-chat
  bind:this={chatRoot}
>
  <header
    class={[
      "border-default flex items-center justify-between gap-2 border-b px-4 py-3",
      config.theme.header_color && "widget-header-tinted"
    ]}
  >
    <div class="flex min-w-0 items-center gap-3">
      {#if config.theme.logo_url && isHttpUrl(config.theme.logo_url)}
        <img
          class="h-8 w-8 shrink-0 rounded-md object-contain"
          src={config.theme.logo_url}
          alt=""
          width="32"
          height="32"
        />
      {:else}
        <!-- Eneo's mark stands in until the organisation sets its own logo. -->
        <span class="flex h-8 w-8 shrink-0 items-center justify-center" aria-hidden="true">
          <IconEneo size="md" class="text-brand-eneo" viewBox="0 -21 214 214" />
        </span>
      {/if}
      <div class="min-w-0">
        <h1 bind:this={title} tabindex="-1" class="text-base font-semibold break-words">
          {config.texts.title || config.name}
        </h1>
        <p class="widget-header-muted text-xs">{subtitle}</p>
      </div>
    </div>
    <div class="flex shrink-0 items-center gap-1">
      {#if messages.length > 0}
        <button
          type="button"
          class="widget-header-button"
          bind:this={startOverButton}
          onclick={() => (confirmStartOver = true)}
          aria-label={m.widget_new_conversation()}
          title={m.widget_new_conversation()}
        >
          <MessageSquarePlus class="size-5" aria-hidden="true" />
        </button>
      {/if}
      {#if canExpand}
        <!-- One control whose name follows its effect, like the launcher's. -->
        <button
          type="button"
          class="widget-header-button"
          onclick={() => (expanded ? bridge.collapse() : bridge.expand())}
          aria-label={expanded ? m.widget_collapse() : m.widget_expand()}
          title={expanded ? m.widget_collapse() : m.widget_expand()}
        >
          {#if expanded}
            <Minimize2 class="size-5" aria-hidden="true" />
          {:else}
            <Maximize2 class="size-5" aria-hidden="true" />
          {/if}
        </button>
      {/if}
      {#if bridge.embedded}
        <button
          type="button"
          class="widget-header-button"
          onclick={() => bridge.close()}
          aria-label={m.widget_close()}
          title={m.widget_close()}
        >
          <X class="size-5" aria-hidden="true" />
        </button>
      {/if}
    </div>
  </header>

  <!-- The conversation is the page's main landmark; header and footer frame it. -->
  <main class="widget-log min-h-0 flex-1 overflow-y-auto px-4 py-4" bind:this={log}>
    <div class="widget-column">
      {#if unavailable}
        <p class="text-secondary text-center text-sm">{m.widget_not_available_body()}</p>
      {:else if messages.length === 0 && !showPending}
        {#if config.texts.welcome}
          <p class="text-primary text-base whitespace-pre-wrap">{config.texts.welcome}</p>
        {/if}
        {#if !busy && draft.length === 0 && config.texts.suggested_questions?.length}
          <ul
            class="widget-suggestions mt-4 flex flex-col gap-2"
            aria-label={m.widget_suggested_questions()}
          >
            {#each config.texts.suggested_questions as suggestion, index (index)}
              <li>
                <button
                  type="button"
                  class="border-default bg-primary text-primary hover:bg-secondary min-h-[44px] w-full rounded-lg border px-3 py-2 text-left text-sm"
                  disabled={unavailable || coolingDown}
                  onclick={() => void send(suggestion)}>{suggestion}</button
                >
              </li>
            {/each}
          </ul>
        {/if}
      {:else}
        <!-- The list keeps its semantics; the log role sits on a wrapper so list
           items stay inside a real list (axe: listitem). Its implicit polite
           live region is switched off: streamed chunks would be read token by
           token, and the announcement region below reports completion. -->
        <div role="log" aria-live="off" aria-label={m.widget_conversation_log()}>
          <ol class="flex flex-col gap-6">
            {#each messages as message, index (index)}
              <WidgetMessage
                {message}
                {index}
                isLast={index === messages.length - 1}
                isLoading={chat.askQuestion.isLoading}
                showSources={config.show_sources ?? true}
                showActivity={config.show_tool_activity ?? true}
              />
            {/each}
            {#if showPending && pendingQuestion !== null}
              <li class="flex flex-col gap-3">
                <WidgetQuestionBubble text={pendingQuestion} />
                <!-- Announced once when the question is sent, not by the dots. -->
                <div aria-hidden="true"><TypingIndicator /></div>
              </li>
            {/if}
          </ol>
        </div>
        {#if !singleTurn && chat.currentConversation.id && rateableSession === chat.currentConversation.id}
          <WidgetFeedback
            sessionId={chat.currentConversation.id}
            collectsText={config.collects_feedback_text}
            restored={chat.currentConversation.feedback ?? null}
            disabled={status === "sending" || chat.askQuestion.isLoading}
            submit={submitFeedback}
          />
        {/if}
      {/if}
    </div>
  </main>

  <div class="sr-only" aria-live="polite" aria-atomic="true">{announcer.text}</div>

  <footer class="border-default border-t px-4 py-3">
    <div class="widget-column flex flex-col gap-2">
      {#if errorMessage}
        <p
          role="alert"
          class="bg-negative-dimmer text-negative-default rounded-lg px-3 py-2 text-sm"
        >
          {errorMessage}
        </p>
      {/if}
      {#if status === "verifying"}
        <p class="text-secondary text-xs">{m.widget_verifying()}</p>
      {/if}
      {#if answered}
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-secondary text-xs">{m.widget_single_turn_hint()}</p>
          <button
            type="button"
            bind:this={newQuestionButton}
            class="widget-new-question bg-primary text-primary hover:bg-secondary flex items-center gap-1.5 border px-3 py-1.5 text-sm"
            onclick={startOver}
          >
            <MessageSquarePlus class="size-4" aria-hidden="true" />
            {m.widget_new_question()}
          </button>
        </div>
      {/if}
      <WidgetComposer
        bind:this={composer}
        placeholder={config.texts.placeholder || m.widget_input_placeholder()}
        maxLength={config.max_question_chars}
        disabled={unavailable || answered || coolingDown}
        {busy}
        bind:value={draft}
        onSend={(question) => void send(question)}
      />
      {#if config.texts.footer_text || config.texts.footer_link_url}
        <p class="text-secondary text-xs">
          {config.texts.footer_text}
          {#if config.texts.footer_link_url && isHttpUrl(config.texts.footer_link_url)}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- external link from widget configuration -->
            <a
              class="underline underline-offset-2"
              href={config.texts.footer_link_url}
              target="_blank"
              rel="noopener noreferrer"
              >{config.texts.footer_link_label || linkHost(config.texts.footer_link_url)}</a
            >
          {/if}
        </p>
      {/if}
    </div>
  </footer>

  <AlertDialog.Root bind:open={confirmStartOver}>
    <AlertDialog.Content class="max-w-[calc(100%-2rem)] sm:max-w-sm">
      <AlertDialog.Header>
        <AlertDialog.Title>{m.widget_new_conversation_confirm_title()}</AlertDialog.Title>
        <AlertDialog.Description>{m.widget_new_conversation_confirm_body()}</AlertDialog.Description
        >
      </AlertDialog.Header>
      <AlertDialog.Footer>
        <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
        <AlertDialog.Action onclick={startOver}
          >{m.widget_new_conversation_confirm_action()}</AlertDialog.Action
        >
      </AlertDialog.Footer>
    </AlertDialog.Content>
  </AlertDialog.Root>

  {#if challengeReady}
    <!-- The server may require a challenge after this iframe was opened. -->
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

<style>
  /* Conversation and composer keep a readable measure when the panel is
     wide: expanded over the host page, or the stand-alone page on a desktop.
     The header stays edge to edge so its controls sit where the panel's
     corners are. In a 400px panel the column is simply the panel. */
  .widget-column {
    width: 100%;
    max-width: 42rem;
    margin-inline: auto;
  }
  .widget-chat {
    overscroll-behavior: contain;
    overflow-y: auto;
  }
  header,
  footer {
    flex-shrink: 0;
  }
  .widget-log {
    /* Keep the conversation flexible when the keyboard shortens the panel.
       A minimum reading area makes oversized text scroll the whole panel
       instead of clipping the header/composer or losing the conversation. */
    min-height: 6rem;
    overscroll-behavior-y: contain;
  }
  footer {
    padding-bottom: max(0.75rem, env(safe-area-inset-bottom));
  }
  @media (pointer: coarse) {
    .widget-chat:has(:global(.widget-composer textarea:focus)) .widget-suggestions {
      display: none;
    }
  }
  /* A tinted header uses the widget's own colours; text is derived for contrast. */
  .widget-header-tinted {
    background: var(--widget-header);
    color: var(--widget-on-header);
    border-color: transparent;
  }
  .widget-header-button {
    display: flex;
    width: max(44px, 2.75rem);
    height: max(44px, 2.75rem);
    align-items: center;
    justify-content: center;
    border-radius: 9999px;
    color: var(--text-primary);
    background: transparent;
  }
  .widget-header-button:hover {
    background: var(--background-secondary);
  }
  .widget-header-button:focus-visible {
    outline: 2px solid currentColor;
    outline-offset: 2px;
  }
  .widget-header-tinted .widget-header-button {
    color: inherit;
  }
  .widget-header-tinted .widget-header-button:hover {
    background: color-mix(in srgb, currentColor 15%, transparent);
  }
  .widget-header-muted {
    color: var(--text-secondary);
  }
  .widget-new-question {
    border-color: var(--widget-accent);
    border-radius: var(--widget-radius);
  }
  /* Full opacity: the derived text colour is what passes the contrast check. */
  .widget-header-tinted .widget-header-muted {
    color: inherit;
  }
</style>
