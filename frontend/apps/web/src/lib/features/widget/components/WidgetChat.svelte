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
  import { IconEneo } from "@eneo/icons/eneo";
  import { launcherColors } from "../contrast";
  import { isHttpUrl, linkHost } from "../urls";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Check, MessageSquarePlus, ThumbsDown, ThumbsUp, X } from "lucide-svelte";
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
  let newQuestionButton = $state<HTMLButtonElement | null>(null);

  let status = $state<"idle" | "verifying" | "sending">("idle");
  let announcement = $state("");
  let errorMessage = $state<string | null>(null);
  let unavailable = $state(false);
  // A 429 with Retry-After: the composer stays closed until the window passes.
  let coolingDown = $state(false);
  let cooldownTimer: ReturnType<typeof setTimeout> | null = null;
  let feedbackGiven = $state<Record<string, 1 | -1>>({});
  // The optional comment after a vote, offered only when the widget stores it.
  let feedbackText = $state("");
  let feedbackTextSent = $state<Record<string, true>>({});
  let sendingFeedbackText = $state(false);
  // Shown while the backend has not yet confirmed the question (first chunk).
  let pendingQuestion = $state<string | null>(null);

  // Props are fixed for the lifetime of the page; capture them once.
  const initial = untrack(() => ({ client, config, hostOrigin, onSession, onTheme, previewToken }));

  const session = new VisitorSession({
    client: initial.client,
    config: initial.config,
    fixedToken: initial.previewToken,
    solve: () => {
      // Restore what was in progress (a send stays "sending" until it ends).
      const before = status;
      status = "verifying";
      return solveWithAltcha(altchaElement).finally(() => {
        if (status === "verifying") status = before;
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
  const subtitle = $derived(config.texts.subtitle);
  // Retention 0: the backend deletes the session when the answer ends, so
  // there is nothing to continue, rate or restore. Each question stands alone.
  const singleTurn = $derived(config.single_turn);
  const answered = $derived(singleTurn && messages.length > 0 && !busy);

  onMount(() => {
    bridge.ready(launcherColors(initial.config.theme));
    if (initial.config.single_turn) {
      session.rememberSession(null);
    } else if (session.sessionId && session.hasIdentity) {
      // Restore the visitor's last conversation on this site, if any.
      void restore(session.sessionId);
    }
    return () => {
      if (cooldownTimer) clearTimeout(cooldownTimer);
      bridge.destroy();
    };
  });

  $effect(() => {
    // The composer closes once a single-turn answer is in; keep the keyboard
    // on the one action that remains instead of dropping focus on the body.
    if (answered) void tick().then(() => newQuestionButton?.focus());
  });

  async function restore(sessionId: string) {
    try {
      await session.ensureToken();
      // ChatService toasts and swallows load errors for the signed-in app;
      // here a gone session must be forgotten, not announced.
      await chat.loadConversation({ id: sessionId }, { rethrow: true });
    } catch (error) {
      // A gone session (retention, a new visitor identity) is not worth showing.
      session.rememberSession(null);
      if (isWidgetUnavailable(error) && !isSessionError(error)) unavailable = true;
    }
  }

  /** Seconds from a 429's Retry-After header, or null when it carries none. */
  function retryAfterSeconds(error: unknown): number | null {
    if (!(error instanceof EneoError) || error.status !== 429) return null;
    const raw = error.headers?.get("retry-after");
    const seconds = raw ? Number.parseInt(raw, 10) : Number.NaN;
    return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
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
    const wait = retryAfterSeconds(error);
    switch (errorCode(error)) {
      case "rate_limited_visitor":
      case "rate_limited_ip":
      case "rate_limited_mint":
      case "rate_limited_challenge":
        return wait !== null && wait <= 600
          ? m.widget_error_rate_limited_wait({ seconds: String(wait) })
          : m.widget_error_rate_limited();
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

  async function send(question: string): Promise<void> {
    // One request at a time. The guard is synchronous, so a second click while
    // the token is minted or before the first chunk never starts another ask.
    if (status !== "idle" || chat.askQuestion.isLoading) return;
    status = "sending";
    errorMessage = null;
    pendingQuestion = question;
    try {
      await ask(question, false);
    } finally {
      status = "idle";
      pendingQuestion = null;
      await tick();
      log?.scrollTo({ top: log.scrollHeight, behavior: "smooth" });
    }
  }

  async function ask(question: string, retried: boolean): Promise<void> {
    const wasNew = !chat.currentConversation.id;
    try {
      await session.ensureToken();
      await chat.askQuestion(question);
      const sessionId = chat.currentConversation.id;
      if (sessionId) {
        if (!singleTurn) session.rememberSession(sessionId);
        // The host page only learns that a conversation began, never its id.
        if (wasNew) bridge.conversationStarted();
      }
      announcement = m.widget_answer_complete();
    } catch (error) {
      if (isTokenRejected(error) && !retried) {
        // Stale after a pause/config change or simply expired: re-mint once.
        session.invalidate();
        return ask(question, true);
      }
      if (errorCode(error) === "widget_not_active") unavailable = true;
      const wait = retryAfterSeconds(error);
      if (wait !== null && wait <= 600) coolDown(wait);
      // The alert below announces the error itself; no second live message.
      errorMessage = describe(error);
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

  async function feedback(value: 1 | -1, retried = false): Promise<void> {
    const sessionId = chat.currentConversation.id;
    if (!sessionId || feedbackGiven[sessionId] === value) return;
    try {
      // A vote often comes minutes after the answer: the token may have
      // expired meanwhile, so it is refreshed like before a question.
      await session.ensureToken();
      await client.conversations.leaveFeedback({
        conversation: { id: sessionId },
        feedback: { value }
      });
      feedbackGiven = { ...feedbackGiven, [sessionId]: value };
    } catch (error) {
      if (isTokenRejected(error) && !retried) {
        session.invalidate();
        return feedback(value, true);
      }
      errorMessage = describe(error);
    }
  }

  async function sendFeedbackText(retried = false): Promise<void> {
    const sessionId = chat.currentConversation.id;
    const value = sessionId ? feedbackGiven[sessionId] : undefined;
    const text = feedbackText.trim();
    if (!sessionId || !value || !text || sendingFeedbackText) return;
    sendingFeedbackText = true;
    try {
      await session.ensureToken();
      await client.conversations.leaveFeedback({
        conversation: { id: sessionId },
        feedback: { value, text }
      });
      feedbackTextSent = { ...feedbackTextSent, [sessionId]: true };
      feedbackText = "";
    } catch (error) {
      if (isTokenRejected(error) && !retried) {
        session.invalidate();
        sendingFeedbackText = false;
        return sendFeedbackText(true);
      }
      errorMessage = describe(error);
    } finally {
      sendingFeedbackText = false;
    }
  }
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div class="bg-primary text-primary flex h-full min-h-0 flex-col" data-widget-chat>
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
        <h1 class="truncate text-base font-semibold">{config.texts.title || config.name}</h1>
        <p class="widget-header-muted text-xs">{subtitle}</p>
      </div>
    </div>
    <div class="flex shrink-0 items-center gap-1">
      {#if messages.length > 0}
        <button
          type="button"
          class="widget-header-button"
          onclick={() => (confirmStartOver = true)}
          aria-label={m.widget_new_conversation()}
          title={m.widget_new_conversation()}
        >
          <MessageSquarePlus class="size-5" aria-hidden="true" />
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

  <div class="min-h-0 flex-1 overflow-y-auto px-4 py-4" bind:this={log}>
    {#if unavailable}
      <p class="text-secondary text-center text-sm">{m.widget_not_available_body()}</p>
    {:else if messages.length === 0 && !showPending}
      {#if config.texts.welcome}
        <p class="text-primary text-base whitespace-pre-wrap">{config.texts.welcome}</p>
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
              showSources={initial.config.show_sources ?? true}
            />
          {/each}
          {#if showPending && pendingQuestion !== null}
            <li class="flex flex-col gap-3">
              <div class="flex justify-end">
                <p class="widget-bubble max-w-[85%] px-4 py-2 text-base whitespace-pre-wrap">
                  <span class="sr-only">{m.widget_you()}: </span>{pendingQuestion}
                </p>
              </div>
              <TypingIndicator />
            </li>
          {/if}
        </ol>
      </div>
      {#if !singleTurn && chat.currentConversation.id && !chat.askQuestion.isLoading}
        {@const given = feedbackGiven[chat.currentConversation.id]}
        <div
          class="mt-3 flex items-center gap-2"
          role="group"
          aria-labelledby="widget-feedback-prompt"
        >
          <span id="widget-feedback-prompt" class="text-secondary text-xs">
            {m.widget_feedback_prompt()}
          </span>
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
            onclick={() => feedback(1)}
          >
            <ThumbsUp class="size-4" aria-hidden="true" />
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
            onclick={() => feedback(-1)}
          >
            <ThumbsDown class="size-4" aria-hidden="true" />
          </button>
        </div>
        {#if given}
          {@const sent = feedbackTextSent[chat.currentConversation.id]}
          <!-- A live status, so the acknowledgement is read out as well as seen. -->
          <p class="text-secondary mt-2 flex items-center gap-1.5 text-xs" role="status">
            <Check class="text-positive-default size-3.5 shrink-0" aria-hidden="true" />
            {sent ? m.widget_feedback_received() : m.widget_feedback_thanks()}
          </p>
          {#if initial.config.collects_feedback_text && !sent}
            <form
              class="mt-2 flex flex-col gap-2"
              onsubmit={(event) => {
                event.preventDefault();
                void sendFeedbackText();
              }}
            >
              <label for="widget-feedback-text" class="text-secondary text-xs">
                {m.widget_feedback_more()}
              </label>
              <textarea
                id="widget-feedback-text"
                class="border-default bg-primary text-primary focus-visible:ring-default w-full resize-y rounded-lg border px-3 py-2 text-sm focus-visible:ring-2 focus-visible:outline-none"
                rows="2"
                maxlength="2000"
                placeholder={m.widget_feedback_more_placeholder()}
                bind:value={feedbackText}></textarea>
              <div>
                <button
                  type="submit"
                  class="widget-feedback-send focus-visible:ring-default rounded-lg px-3 py-1.5 text-sm font-medium focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50"
                  disabled={!feedbackText.trim() || sendingFeedbackText}
                >
                  {m.widget_feedback_send()}
                </button>
              </div>
            </form>
          {/if}
        {/if}
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
    {#if answered}
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-secondary text-xs">{m.widget_single_turn_hint()}</p>
        <button
          type="button"
          bind:this={newQuestionButton}
          class="widget-new-question bg-primary text-primary hover:bg-secondary focus-visible:ring-default flex items-center gap-1.5 border px-3 py-1.5 text-sm focus-visible:ring-2 focus-visible:outline-none"
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
      suggestions={config.texts.suggested_questions ?? []}
      showSuggestions={messages.length === 0}
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

<style>
  .widget-feedback-send {
    background: var(--widget-accent);
    color: var(--widget-on-accent);
  }

  /* A tinted header uses the widget's own colours; text is derived for contrast. */
  .widget-header-tinted {
    background: var(--widget-header);
    color: var(--widget-on-header);
    border-color: transparent;
  }
  .widget-header-button {
    display: flex;
    width: 2.25rem;
    height: 2.25rem;
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
  .widget-bubble {
    background: var(--widget-accent);
    color: var(--widget-on-accent);
    border-radius: var(--widget-radius);
    border-bottom-right-radius: 4px;
  }
  /* Full opacity: the derived text colour is what passes the contrast check. */
  .widget-header-tinted .widget-header-muted {
    color: inherit;
  }
</style>
