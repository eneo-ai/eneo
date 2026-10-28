"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import type { WidgetClient, WidgetPublicConfig } from "@eneo/eneo-js";
import { Maximize2, MessageSquarePlus, Minimize2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { loadAltcha, solveWithAltcha } from "../altcha";
import { answerText } from "../answer-text";
import { launcherColors } from "../contrast";
import { createEmbedBridge, type EmbedBridge, type PanelLayout } from "../embed-bridge";
import type { PersonaView } from "../persona";
import { isHttpUrl, linkHost } from "../urls";
import { VisitorSession, isTokenRejected, isWidgetUnavailable } from "../visitor-session";
import {
  MAX_COOLDOWN_SECONDS,
  describeWidgetError,
  isSessionError,
  retryAfterSeconds,
  widgetErrorCode
} from "../widget-errors";
import { cn } from "@/lib/utils";
import { TypingIndicator } from "./typing-indicator";
import { useWidgetConversation } from "./use-widget-conversation";
import { WidgetComposer, type WidgetComposerHandle } from "./widget-composer";
import { WidgetFeedback } from "./widget-feedback";
import { WidgetMessage } from "./widget-message";
import { WidgetPersonaByline } from "./widget-persona-byline";
import { WidgetQuestionBubble } from "./widget-question-bubble";

type Scheme = "light" | "dark" | "auto";
type Status = "idle" | "verifying" | "sending";

const subscribeNever = () => () => {};

/** The hidden proof-of-work element, created once it is first needed. */
type AltchaElement = import("altcha/external").AltchaWidgetElement;

/**
 * The chat a visitor sees inside the widget iframe (or on the stand-alone
 * page). Everything visible is widget-specific so the WCAG contract of the
 * widget (ADR) is enforced here, the same as in the SvelteKit app.
 */
export function WidgetChat({
  config,
  client,
  hostOrigin,
  onSession,
  onTheme,
  previewToken = null,
  persona = null
}: {
  config: WidgetPublicConfig;
  client: WidgetClient;
  hostOrigin: string | null;
  onSession: (session: VisitorSession) => void;
  /** The host page's colour scheme, forwarded by the loader. */
  onTheme?: (scheme: Scheme) => void;
  /** Admin preview of a draft widget: used as the visitor token, nothing is remembered. */
  previewToken?: string | null;
  /** The voice answers are presented under; null for a neutral widget. */
  persona?: PersonaView | null;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const {
    conversation,
    asking,
    loading: restoring,
    ask,
    load,
    reset
  } = useWidgetConversation(client);
  const messages = conversation.messages;
  // What the handlers continue from; they run after commit.
  const conversationRef = useRef(conversation);
  useEffect(() => {
    conversationRef.current = conversation;
  }, [conversation]);

  const composer = useRef<WidgetComposerHandle>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const chatRoot = useRef<HTMLDivElement>(null);
  const log = useRef<HTMLElement>(null);
  const newQuestionButton = useRef<HTMLButtonElement>(null);
  const startOverButton = useRef<HTMLButtonElement>(null);
  const altchaHost = useRef<HTMLDivElement>(null);
  const altcha = useRef<Promise<AltchaElement> | null>(null);
  const cooldownTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [draft, setDraft] = useState("");
  // How the loader shows the panel; null until a loader that reports it says.
  const [layout, setLayout] = useState<PanelLayout | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const statusRef = useRef<Status>("idle");
  useEffect(() => {
    statusRef.current = status;
  }, [status]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  // A 429 with Retry-After: the composer stays closed until the window passes.
  const [coolingDown, setCoolingDown] = useState(false);
  // Shown while the backend has not yet confirmed the question (first chunk).
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  // How many messages there were when it was sent; the same text asked again
  // must still show as pending, so the count tells when it has arrived.
  const [pendingFrom, setPendingFrom] = useState(0);
  // The conversation whose first answer is in. Its feedback stays mounted
  // through follow-up questions, so a vote is not lost to the next one.
  const [rateableSession, setRateableSession] = useState<string | null>(null);
  // Starting over throws the visible conversation away, so it asks first.
  const [confirmStartOver, setConfirmStartOver] = useState(false);

  /**
   * The ALTCHA element, mounted hidden on first use: it fetches the
   * challenge from the widget's challenge URL itself (through this origin's
   * proxy) and solves it in workers. Loaded on the client only, as a custom
   * element has no server side.
   */
  const ensureAltcha = useCallback((): Promise<AltchaElement> => {
    altcha.current ??= loadAltcha().then(async () => {
      const element = document.createElement("altcha-widget") as AltchaElement;
      // Its settings are attributes named after its properties. The element
      // fetches the challenge itself, so it needs the real address under
      // this page's origin, not the client's relative one.
      element.setAttribute(
        "challenge",
        `${window.location.origin}/api/v1/widgets/${encodeURIComponent(config.public_id)}/challenge/`
      );
      element.setAttribute("auto", "off");
      element.setAttribute("display", "invisible");
      element.setAttribute("workers", "2");
      element.setAttribute(
        "configuration",
        JSON.stringify({ hideFooter: true, hideLogo: true, workers: 2, credentials: "omit" })
      );
      altchaHost.current?.appendChild(element);
      // A Svelte custom element mounts a tick after it is connected; its
      // methods (verify, reset) exist from then on.
      await new Promise((resolve) => setTimeout(resolve, 0));
      return element;
    });
    return altcha.current;
  }, [config.public_id]);

  const [session] = useState(
    () =>
      new VisitorSession({
        client,
        config,
        fixedToken: previewToken,
        solve: async () => {
          // Restore what was in progress (a send stays "sending" until it ends).
          const before = statusRef.current;
          setStatus("verifying");
          const element = await ensureAltcha();
          return solveWithAltcha(element).finally(() => {
            if (statusRef.current === "verifying") setStatus(before);
          });
        }
      })
  );

  // The loader's messages arrive on a bridge created once; the handlers read
  // the latest state through this ref, refreshed after every commit.
  const subtitle = config.texts.subtitle;
  const handlers = useRef<{
    onOpen: () => void;
    onTheme: (scheme: Scheme) => void;
    onLayout: (layout: PanelLayout) => void;
  }>({ onOpen: () => {}, onTheme: () => {}, onLayout: () => {} });
  const latestHandlers: typeof handlers.current = {
    onOpen: () => {
      // A touch device should open the conversation before its keyboard.
      // The heading gives screen readers context without panning the iframe.
      if (matchMedia("(pointer: coarse)").matches) title.current?.focus({ preventScroll: true });
      else composer.current?.focus();
      // Focus lands past the header, so the AI disclosure under the title
      // would never be read; say it with the title each time the chat opens.
      announce(`${config.texts.title || config.name}. ${subtitle}`);
    },
    onTheme: (scheme) => onTheme?.(scheme),
    onLayout: (next) => {
      setLayout((before) => {
        // The control's name follows the new state; a screen reader also
        // hears that the request took effect. The first layout is not news.
        if (before && before.expanded !== next.expanded) {
          announce(
            next.expanded ? t("widget_expanded_announced") : t("widget_collapsed_announced")
          );
        }
        return next;
      });
    }
  };
  useEffect(() => {
    handlers.current = latestHandlers;
  });
  // Inside the loader's iframe, or on the stand-alone page: fixed for the
  // page's lifetime, known in the browser only.
  const embedded = useSyncExternalStore(
    subscribeNever,
    () => hostOrigin !== null && window.parent !== window,
    () => false
  );
  const bridge = useRef<EmbedBridge | null>(null);

  // Expand grows the panel over the host page on a wide screen; on a small
  // screen the loader already fills the viewport, so there is nothing to offer.
  const expanded = layout?.expanded ?? false;
  const canExpand = embedded && layout !== null && (!layout.full || expanded);

  // The question is appended once the backend confirms it; until then show
  // it and a typing indicator so the visitor sees progress.
  const showPending = pendingQuestion !== null && messages.length <= pendingFrom;
  const busy = restoring || status !== "idle" || asking;
  // With a persona the welcome text is its first message (see the log below).
  const opening = persona && config.texts.welcome ? config.texts.welcome : null;
  // Retention 0: the backend deletes the session when the answer ends, so
  // there is nothing to continue, rate or restore. Each question stands alone.
  const singleTurn = config.single_turn;
  const answered = singleTurn && messages.length > 0 && !busy;

  // A long description is clamped to two lines in the header; the toggle is
  // offered only while something is actually hidden. Screen readers get the
  // whole text either way, the clamp is visual.
  const subtitleEl = useRef<HTMLParagraphElement>(null);
  const [subtitleOpen, setSubtitleOpen] = useState(false);
  const [subtitleOverflows, setSubtitleOverflows] = useState(false);
  useEffect(() => {
    const el = subtitleEl.current;
    if (!el || subtitleOpen || typeof ResizeObserver === "undefined") return;
    const measure = () => setSubtitleOverflows(el.scrollHeight > el.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [subtitleOpen, subtitle]);

  /** The conversation scrolls, or on a short panel the whole chat does. */
  const scrollToEnd = useCallback(() => {
    const behavior = matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    for (const scroller of [log.current, chatRoot.current]) {
      if (typeof scroller?.scrollTo === "function") {
        scroller.scrollTo({ top: scroller.scrollHeight, behavior });
      }
    }
  }, []);

  const restore = useCallback(
    async (sessionId: string, retried = false): Promise<void> => {
      try {
        await session.ensureToken();
        await load(sessionId);
        setRateableSession(sessionId);
      } catch (error) {
        if (isTokenRejected(error) && !retried) {
          // Stale after a pause or a settings change: a fresh token for the
          // same visitor still owns the conversation.
          session.invalidate();
          return restore(sessionId, true);
        }
        // A gone session (retention, a new visitor identity) is not worth showing.
        session.rememberSession(null);
        if (isWidgetUnavailable(error) && !isSessionError(error)) setUnavailable(true);
      }
    },
    [session, load]
  );

  useEffect(() => {
    onSession(session);
    const created = createEmbedBridge({
      hostOrigin,
      handlers: {
        onOpen: () => handlers.current.onOpen(),
        onTheme: (scheme: Scheme) => handlers.current.onTheme(scheme),
        onLayout: (next: PanelLayout) => handlers.current.onLayout(next)
      }
    });
    bridge.current = created;
    created.ready(
      launcherColors(config.theme),
      config.texts.title || config.name,
      persona
        ? {
            name: persona.name,
            // The launcher lives on the host page, so the avatar's address
            // must be absolute there: the loader drops anything but http(s).
            avatar_url:
              persona.inLauncher && persona.avatarUrl
                ? new URL(persona.avatarUrl, location.origin).href
                : null
          }
        : undefined
    );
    if (config.bot_protection === "altcha") void ensureAltcha();
    if (config.single_turn) {
      session.rememberSession(null);
    } else if (session.sessionId && session.hasIdentity) {
      // Restore the visitor's last conversation on this site, if any.
      void restore(session.sessionId);
    }
    return () => {
      if (cooldownTimer.current) clearTimeout(cooldownTimer.current);
      created.destroy();
      bridge.current = null;
    };
    // Props are fixed for the lifetime of the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The composer closes once a single-turn answer is in; keep the keyboard
  // on the one action that remains instead of dropping focus on the body.
  useEffect(() => {
    if (answered) newQuestionButton.current?.focus();
  }, [answered]);

  // Escape closes the panel from anywhere inside it, not only the textarea;
  // the confirm dialog handles its own Escape first and marks it as used.
  useEffect(() => {
    const onKeydown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || confirmStartOver) return;
      if (!embedded) return;
      event.preventDefault();
      // Leaving the enlarged layout comes first, as with full screen elsewhere;
      // a second Escape closes the chat.
      if (expanded) bridge.current?.collapse();
      else bridge.current?.close();
    };
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  }, [embedded, expanded, confirmStartOver]);

  function coolDown(seconds: number) {
    setCoolingDown(true);
    if (cooldownTimer.current) clearTimeout(cooldownTimer.current);
    cooldownTimer.current = setTimeout(() => {
      setCoolingDown(false);
      setErrorMessage(null);
    }, seconds * 1000);
  }

  /** The turn exists on the server: remember it and tell the host page one began. */
  function keepConversation(wasNew: boolean, sessionId: string) {
    if (!singleTurn) session.rememberSession(sessionId);
    // The host page only learns that a conversation began, never its id.
    if (wasNew) bridge.current?.conversationStarted();
    setRateableSession(sessionId);
  }

  async function askQuestion(question: string, retried: boolean): Promise<void> {
    const wasNew = !conversationRef.current.id;
    let result: Awaited<ReturnType<typeof ask>>;
    try {
      await session.ensureToken();
      result = await ask(question);
    } catch (error) {
      result = { status: "failed", error, started: false };
    }
    if (result.status === "done") {
      keepConversation(wasNew, result.sessionId);
      // The finished answer is read once, as in any chat; the stream never
      // is (the log's own live region is off).
      const answer = answerText(result.answer);
      const sender = persona?.name ?? t("widget_assistant");
      announce(answer ? `${sender}: ${answer}` : t("widget_answer_complete"));
      return;
    }
    const { error } = result;
    if (result.started && result.sessionId) {
      // The answer broke off after it began: what arrived stays, the alert
      // says it is incomplete and nothing announces it as done.
      keepConversation(wasNew, result.sessionId);
      setErrorMessage(t("widget_error_incomplete"));
      return;
    }
    if (isTokenRejected(error) && !retried) {
      // Stale after a pause/config change or simply expired: re-mint once.
      session.invalidate();
      return askQuestion(question, true);
    }
    // Nothing reached the server, so the question goes back into the field.
    composer.current?.restore(question);
    const code = widgetErrorCode(error);
    // The visitor gets a generic sentence; whoever runs the site gets the cause.
    if (code === null) console.error(error);
    if (code === "widget_not_active") setUnavailable(true);
    if (code === "session_not_owned") {
      // Deleted by retention, or owned by an identity this browser lost:
      // asking in it again can never succeed.
      reset();
      session.rememberSession(null);
      setErrorMessage(t("widget_error_session_gone"));
      return;
    }
    const wait = retryAfterSeconds(error);
    if (wait !== null && wait <= MAX_COOLDOWN_SECONDS) coolDown(wait);
    // The alert announces the error itself; no second live message.
    setErrorMessage(describeWidgetError(error, t));
    // The conversation is full: the one way on is to start a new one.
    if (code === "session_turns_exceeded") {
      requestAnimationFrame(() => startOverButton.current?.focus());
    }
  }

  async function send(question: string): Promise<void> {
    // One request at a time. The guard is synchronous, so a second click while
    // the token is minted or before the first chunk never starts another ask.
    if (restoring || statusRef.current !== "idle" || asking) return;
    // A suggested question leaves the page with the question; focus must not
    // go with it. The composer takes it, or on a touch screen the heading,
    // so the keyboard does not open over the answer.
    if (document.activeElement?.closest(".widget-suggestions")) {
      if (matchMedia("(pointer: coarse)").matches) title.current?.focus({ preventScroll: true });
      else composer.current?.focus();
    }
    statusRef.current = "sending";
    setStatus("sending");
    setErrorMessage(null);
    setPendingQuestion(question);
    setPendingFrom(conversationRef.current.messages.length);
    // The typing dots are silent; this tells a screen reader the question went off.
    announce(
      persona ? t("widget_persona_answering", { name: persona.name }) : t("assistant_is_typing")
    );
    try {
      await askQuestion(question, false);
    } finally {
      statusRef.current = "idle";
      setStatus("idle");
      setPendingQuestion(null);
      requestAnimationFrame(scrollToEnd);
    }
  }

  function startOver() {
    setConfirmStartOver(false);
    reset();
    session.rememberSession(null);
    setErrorMessage(null);
    setRateableSession(null);
    requestAnimationFrame(() => composer.current?.focus());
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
    const sessionId = conversationRef.current.id;
    if (!sessionId) return t("widget_error_generic");
    // Feedback owns the next error location, just as sending a question
    // clears an older feedback error. Never keep two attempts' alerts.
    setErrorMessage(null);
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
      return describeWidgetError(error, t);
    }
  }

  return (
    <div
      className="widget-chat bg-ax-surface text-ax-text flex h-full min-h-0 flex-col"
      data-widget-chat
      ref={chatRoot}
    >
      <header
        className={cn(
          "border-ax-border flex items-center justify-between gap-2 border-b px-4 py-3",
          config.theme.header_color && "widget-header-tinted"
        )}
      >
        <div className="flex min-w-0 items-center gap-3">
          {/* The header is the organisation's: its title and disclosure, never
              Eneo's own mark. Who answers is the persona's business, inside the
              conversation. */}
          <div className="min-w-0">
            <h1 ref={title} tabIndex={-1} className="text-base font-semibold break-words">
              {config.texts.title || config.name}
            </h1>
            <p
              id="widget-subtitle"
              ref={subtitleEl}
              className={cn(
                "widget-header-muted widget-subtitle",
                !subtitleOpen && "widget-subtitle-clamped"
              )}
            >
              {subtitle}
            </p>
            {(subtitleOverflows || subtitleOpen) && (
              <button
                type="button"
                className="widget-subtitle-toggle"
                aria-expanded={subtitleOpen}
                aria-controls="widget-subtitle"
                onClick={() => setSubtitleOpen((value) => !value)}
              >
                {subtitleOpen ? t("widget_subtitle_less") : t("widget_subtitle_more")}
              </button>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {messages.length > 0 && (
            <button
              type="button"
              className="widget-header-button"
              ref={startOverButton}
              onClick={() => setConfirmStartOver(true)}
              aria-label={t("widget_new_conversation")}
              title={t("widget_new_conversation")}
            >
              <MessageSquarePlus className="size-5" aria-hidden="true" />
            </button>
          )}
          {canExpand && (
            // One control whose name follows its effect, like the launcher's.
            <button
              type="button"
              className="widget-header-button"
              onClick={() => (expanded ? bridge.current?.collapse() : bridge.current?.expand())}
              aria-label={expanded ? t("widget_collapse") : t("widget_expand")}
              title={expanded ? t("widget_collapse") : t("widget_expand")}
            >
              {expanded ? (
                <Minimize2 className="size-5" aria-hidden="true" />
              ) : (
                <Maximize2 className="size-5" aria-hidden="true" />
              )}
            </button>
          )}
          {embedded && (
            <button
              type="button"
              className="widget-header-button"
              onClick={() => bridge.current?.close()}
              aria-label={t("widget_close")}
              title={t("widget_close")}
            >
              <X className="size-5" aria-hidden="true" />
            </button>
          )}
        </div>
      </header>

      {/* The conversation is the page's main landmark; header and footer frame it. */}
      <main className="widget-log min-h-0 flex-1 overflow-y-auto px-4 py-4" ref={log}>
        <div className="widget-column">
          {unavailable ? (
            <p className="text-ax-text-secondary text-center text-sm">
              {t("widget_not_available_body")}
            </p>
          ) : (
            <>
              {(opening || messages.length > 0 || showPending) && (
                // The list keeps its semantics; the log role sits on a wrapper
                // so list items stay inside a real list. Its implicit polite
                // live region is switched off: streamed chunks would be read
                // token by token, and the chat announces completion itself.
                <div role="log" aria-live="off" aria-label={t("widget_conversation_log")}>
                  <ol className="flex flex-col gap-6">
                    {opening && persona && (
                      // The welcome text is the persona's first message: the
                      // same form as every answer, first in the conversation,
                      // and it stays while the conversation runs.
                      <li className="flex flex-col gap-2">
                        <WidgetPersonaByline persona={persona} />
                        <p className="text-ax-text text-base whitespace-pre-wrap">{opening}</p>
                      </li>
                    )}
                    {messages.map((message, index) => (
                      <WidgetMessage
                        key={index}
                        message={message}
                        index={index}
                        isLast={index === messages.length - 1}
                        isLoading={asking}
                        showSources={config.show_sources ?? true}
                        showActivity={config.show_tool_activity ?? true}
                        persona={persona}
                      />
                    ))}
                    {showPending && pendingQuestion !== null && (
                      <li className="widget-enter flex flex-col gap-3">
                        <WidgetQuestionBubble text={pendingQuestion} />
                        <div>
                          {persona && <WidgetPersonaByline persona={persona} />}
                          {/* Announced once when the question is sent, not by the dots. */}
                          <TypingIndicator />
                        </div>
                      </li>
                    )}
                  </ol>
                </div>
              )}
              {messages.length === 0 && !showPending && (
                <>
                  {/* Without a persona the welcome text is a plain opening
                      paragraph that goes with the first question; it stays
                      out while a stored conversation is being restored. */}
                  {!persona && config.texts.welcome && !restoring && (
                    <p className="text-ax-text text-base whitespace-pre-wrap">
                      {config.texts.welcome}
                    </p>
                  )}
                  {!busy && draft.length === 0 && !!config.texts.suggested_questions?.length && (
                    <ul
                      className="widget-suggestions mt-4 flex flex-col gap-2"
                      aria-label={t("widget_suggested_questions")}
                    >
                      {config.texts.suggested_questions.map((suggestion, index) => (
                        <li key={index}>
                          <button
                            type="button"
                            className="border-ax-border bg-ax-surface text-ax-text hover:bg-ax-hover min-h-[44px] w-full rounded-lg border px-3 py-2 text-left text-sm"
                            disabled={unavailable || coolingDown}
                            onClick={() => void send(suggestion)}
                          >
                            {suggestion}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
              {!singleTurn && conversation.id && rateableSession === conversation.id && (
                <WidgetFeedback
                  sessionId={conversation.id}
                  collectsText={config.collects_feedback_text}
                  restored={conversation.feedback}
                  disabled={status === "sending" || asking}
                  submit={submitFeedback}
                />
              )}
            </>
          )}
        </div>
      </main>

      <footer className="border-ax-border border-t px-4 py-3">
        <div className="widget-column flex flex-col gap-2">
          {errorMessage && (
            <p role="alert" className="bg-ax-error-muted text-ax-red rounded-lg px-3 py-2 text-sm">
              {errorMessage}
            </p>
          )}
          {status === "verifying" && (
            <p className="text-ax-text-secondary text-xs">{t("widget_verifying")}</p>
          )}
          {answered && (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-ax-text-secondary text-xs">{t("widget_single_turn_hint")}</p>
              <button
                type="button"
                ref={newQuestionButton}
                className="widget-new-question bg-ax-surface text-ax-text hover:bg-ax-hover flex items-center gap-1.5 border px-3 py-1.5 text-sm"
                onClick={startOver}
              >
                <MessageSquarePlus className="size-4" aria-hidden="true" />
                {t("widget_new_question")}
              </button>
            </div>
          )}
          <WidgetComposer
            ref={composer}
            placeholder={config.texts.placeholder || t("widget_input_placeholder")}
            maxLength={config.max_question_chars}
            disabled={unavailable || answered || coolingDown}
            busy={busy}
            value={draft}
            onChange={setDraft}
            onSend={(question) => void send(question)}
          />
          {(config.texts.footer_text || config.texts.footer_link_url) && (
            <p className="text-ax-text-secondary text-[0.8rem]">
              {config.texts.footer_text}{" "}
              {config.texts.footer_link_url && isHttpUrl(config.texts.footer_link_url) && (
                <a
                  className="underline underline-offset-2"
                  href={config.texts.footer_link_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {config.texts.footer_link_label || linkHost(config.texts.footer_link_url)}
                </a>
              )}
            </p>
          )}
        </div>
      </footer>

      <AlertDialog
        isOpen={confirmStartOver}
        onOpenChange={setConfirmStartOver}
        title={t("widget_new_conversation_confirm_title")}
        description={t("widget_new_conversation_confirm_body")}
        actionLabel={t("widget_new_conversation_confirm_action")}
        actionVariant="primary"
        cancelLabel={t("cancel")}
        onAction={startOver}
      />

      {/* The proof-of-work element lives here, hidden; the server may require
          a challenge after this iframe was opened. */}
      <div ref={altchaHost} hidden aria-hidden="true" />
    </div>
  );
}
