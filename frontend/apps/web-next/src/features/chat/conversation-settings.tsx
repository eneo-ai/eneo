import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import {
  readConversationDraft,
  rememberConversationDraft,
  resolveConversationDraft
} from "@eneo/eneo-js/conversations/draft-preferences";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { ChatPartner } from "@/lib/chat/types";

/** ErrorCodes.PERSONAL_SKILLS_REJECTED: the change would pause the person's own Skills. */
export const PERSONAL_SKILLS_REJECTED = 9080;

type Settings = Schema<"ConversationSettings">;
type Resolution = Schema<"ConversationSettingsResolution">;
type State = Schema<"ConversationSettingsState">;

/** The settings as the last read or save left them, for work that runs between renders. */
export type ConversationSettingsSnapshot = { resolution: Resolution | null; error: unknown };

type ConversationSettingsContext = {
  resolution: Resolution | null;
  busy: boolean;
  error: unknown;
  /** A change refused because it would pause the person's own Skills: nothing was saved. */
  refusal: EneoApiError | null;
  /** Whether a read or save that shows as busy has yet to finish. */
  pending: () => boolean;
  snapshot: () => ConversationSettingsSnapshot;
  /** Resolves once every queued read and save has run, with what they left. */
  settled: () => Promise<ConversationSettingsSnapshot>;
  hasMessages: boolean;
  running: boolean;
  setRunning: (running: boolean) => void;
  reload: () => Promise<void>;
  /** Re-reads in the background: the shown choices stay until the new ones land, and a failure is ignored. */
  refresh: () => Promise<void>;
  update: (patch: Partial<Settings>) => Promise<void>;
  adoptSession: (id: string, state: State | null | undefined) => void;
  /** Starts a new conversation whose draft begins with these choices on top of the current ones. */
  startConversation: ((patch: Partial<Settings>) => void) | null;
};
const Context = createContext<ConversationSettingsContext | null>(null);

/** A patch carries only the tool states it changes; the maps are merged, not replaced. */
function withPatch(settings: Settings, patch: Partial<Settings>): Settings {
  const next = { ...settings, ...patch };
  if (patch.mcp_server_states)
    next.mcp_server_states = { ...settings.mcp_server_states, ...patch.mcp_server_states };
  if (patch.capability_states)
    next.capability_states = { ...settings.capability_states, ...patch.capability_states };
  return next;
}

/** Saved conversations own their choices; browser preferences seed only new drafts. */
export function ConversationSettingsProvider({
  partner,
  initialSessionId,
  hasHistory = false,
  onNewConversation,
  children
}: {
  partner: ChatPartner;
  initialSessionId?: string | null;
  hasHistory?: boolean;
  onNewConversation?: (prepare?: () => void) => void;
  children: ReactNode;
}) {
  const { user, tenant } = useAppContext();
  const scope = {
    tenantId: tenant.id,
    userId: user.id,
    partnerId: partner.id,
    partnerType: partner.type
  };
  const [resolution, setResolution] = useState<Resolution | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [refusal, setRefusal] = useState<EneoApiError | null>(null);
  const [hasMessages, setHasMessages] = useState(hasHistory);
  const [running, setRunning] = useState(false);
  const sessionId = useRef(initialSessionId ?? null);
  const current = useRef<Resolution | null>(null);
  const failure = useRef<unknown>(null);
  // Reads and saves run one after another, each on top of the latest
  // revision, so a change made during a save is sent after it, not dropped.
  const chain = useRef<Promise<void>>(Promise.resolve());
  const saving = useRef(0);
  const mounted = useRef(false);
  function target() {
    return sessionId.current
      ? { session_id: sessionId.current }
      : partner.type === "group-chat"
        ? { group_chat_id: partner.id }
        : { assistant_id: partner.id };
  }

  function install(next: Resolution) {
    if (!mounted.current) return;
    current.current = next;
    setResolution(next);
  }

  function fail(cause: unknown) {
    failure.current = cause;
    if (mounted.current) setError(cause);
  }

  function refuse(cause: EneoApiError | null) {
    if (mounted.current) setRefusal(cause);
  }

  // The browser's start choices follow what the user set up: a change made
  // in a draft or in a conversation. Opening a conversation or a draft only
  // reads choices and leaves the browser's alone.
  function remember(next: Resolution) {
    if (next.settings_compatible !== false && !next.model_unavailable) {
      rememberConversationDraft(scope, next.settings);
    }
  }

  async function resolve(settings?: Settings) {
    return unwrap(
      browserApi.POST("/api/v1/conversations/settings/resolve/", {
        body: { ...target(), settings: sessionId.current ? undefined : settings }
      })
    );
  }

  async function readSettings() {
    let next = sessionId.current
      ? await resolve()
      : await resolveConversationDraft(
          resolve,
          current.current?.settings ?? readConversationDraft(scope)
        );
    if (sessionId.current && next.revision === 0 && !next.model_unavailable) {
      try {
        await unwrap(
          browserApi.PATCH("/api/v1/conversations/{session_id}/settings/", {
            params: { path: { session_id: sessionId.current } },
            body: { expected_revision: 0, settings: next.settings }
          })
        );
      } catch (cause) {
        if (!(cause instanceof EneoApiError) || cause.status !== 409) throw cause;
      }
      next = await resolve();
    }
    return next;
  }

  /** Queues work behind what is already running; `quiet` work never shows as busy. */
  function enqueue(task: () => Promise<void>, { quiet = false } = {}) {
    if (!quiet) {
      saving.current += 1;
      if (mounted.current) setBusy(true);
    }
    const run = chain.current.then(task).finally(() => {
      if (quiet) return;
      saving.current -= 1;
      if (saving.current === 0 && mounted.current) setBusy(false);
    });
    chain.current = run.catch(() => {});
    return run;
  }

  function load() {
    return enqueue(() =>
      readSettings().then(
        (next) => {
          install(next);
          fail(null);
          refuse(null);
        },
        (cause: unknown) => fail(cause)
      )
    );
  }

  function reload() {
    return load();
  }

  // Nothing was saved, so a failure changes nothing: the next send or save
  // reads again if the revision moved (409).
  function refresh() {
    return enqueue(() => readSettings().then(install, () => {}), { quiet: true });
  }

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
    };
    // ChatView remounts when its conversation or partner changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function update(patch: Partial<Settings>) {
    if (running) return Promise.resolve();
    return enqueue(async () => {
      if (!current.current || current.current.settings_compatible === false) return;
      fail(null);
      refuse(null);
      const settings = withPatch(current.current.settings, patch);
      try {
        if (sessionId.current) {
          const state = await unwrap(
            browserApi.PATCH("/api/v1/conversations/{session_id}/settings/", {
              params: { path: { session_id: sessionId.current } },
              body: { expected_revision: current.current.revision, settings }
            })
          );
          install({ ...current.current, ...state });
        }
        // A draft is normalized like a remembered one: a reasoning level
        // queued behind a model change may not exist on the model that won.
        const next = sessionId.current
          ? await resolve(settings)
          : await resolveConversationDraft(resolve, settings);
        install(next);
        remember(next);
      } catch (cause) {
        if (cause instanceof EneoApiError && cause.code === PERSONAL_SKILLS_REJECTED) refuse(cause);
        else fail(cause);
      }
    });
  }

  function snapshot() {
    return { resolution: current.current, error: failure.current };
  }

  async function settled() {
    // Work queued while waiting (a reload after a conflict) is waited for too.
    let tail: Promise<void>;
    do {
      tail = chain.current;
      await tail;
    } while (tail !== chain.current);
    return snapshot();
  }

  function adoptSession(id: string, state: State | null | undefined) {
    sessionId.current = id;
    setHasMessages(true);
    if (state && current.current) install({ ...current.current, ...state });
    else void reload();
  }

  // Remembered only once leaving is confirmed: a cancelled leave keeps the old start choices.
  const startConversation = onNewConversation
    ? (patch: Partial<Settings>) =>
        onNewConversation(() => {
          if (current.current)
            rememberConversationDraft(scope, withPatch(current.current.settings, patch));
        })
    : null;

  return (
    <Context
      value={{
        resolution,
        busy,
        error,
        refusal,
        pending: () => saving.current > 0,
        snapshot,
        settled,
        hasMessages,
        running,
        setRunning,
        reload,
        refresh,
        update,
        adoptSession,
        startConversation
      }}
    >
      {children}
    </Context>
  );
}

export function useConversationSettings() {
  const context = useContext(Context);
  if (!context) throw new Error("Conversation settings require a conversation provider.");
  return context;
}

/**
 * The model a conversation's turns run on: null while its settings load,
 * undefined outside a conversation or when it has none to run on.
 */
export function useConversationModel(): string | null | undefined {
  const context = useContext(Context);
  if (!context) return undefined;
  if (context.resolution) return context.resolution.effective_model?.id ?? undefined;
  // A failed read leaves nothing to wait for.
  return context.error ? undefined : null;
}

/**
 * Waits for the conversation's queued reads and saves, then gives the model
 * its turns run on (see useConversationModel); undefined outside a conversation.
 */
export function useSettledConversationModel(): (() => Promise<string | undefined>) | undefined {
  const context = useContext(Context);
  if (!context) return undefined;
  const { settled } = context;
  return async () => (await settled()).resolution?.effective_model?.id ?? undefined;
}

/** Interactive views outside a conversation always ask before executing a tool. */
export function useAutomaticConversationTools() {
  const context = useContext(Context);
  return Boolean(
    context?.resolution &&
    !context.busy &&
    !context.error &&
    context.resolution.settings_compatible !== false &&
    context.resolution.settings.require_tool_approval === false
  );
}
