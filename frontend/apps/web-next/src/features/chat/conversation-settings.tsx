"use client";

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

type Settings = Schema<"ConversationSettings">;
type Resolution = Schema<"ConversationSettingsResolution">;
type State = Schema<"ConversationSettingsState">;

type ConversationSettingsContext = {
  resolution: Resolution | null;
  busy: boolean;
  error: unknown;
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
  onNewConversation?: () => void;
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
  const [hasMessages, setHasMessages] = useState(hasHistory);
  const [running, setRunning] = useState(false);
  const sessionId = useRef(initialSessionId ?? null);
  const current = useRef<Resolution | null>(null);
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
          if (mounted.current) setError(null);
        },
        (cause: unknown) => {
          if (mounted.current) setError(cause);
        }
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
      if (mounted.current) setError(null);
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
        if (mounted.current) setError(cause);
      }
    });
  }

  function adoptSession(id: string, state: State | null | undefined) {
    sessionId.current = id;
    setHasMessages(true);
    if (state && current.current) install({ ...current.current, ...state });
    else void reload();
  }

  const startConversation = onNewConversation
    ? (patch: Partial<Settings>) => {
        if (current.current)
          rememberConversationDraft(scope, withPatch(current.current.settings, patch));
        onNewConversation();
      }
    : null;

  return (
    <Context
      value={{
        resolution,
        busy,
        error,
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
