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
  update: (patch: Partial<Settings>) => Promise<void>;
  adoptSession: (id: string, state: State | null | undefined) => void;
};
const Context = createContext<ConversationSettingsContext | null>(null);

/** Saved conversations own their choices; browser preferences seed only new drafts. */
export function ConversationSettingsProvider({
  partner,
  initialSessionId,
  hasHistory = false,
  children
}: {
  partner: ChatPartner;
  initialSessionId?: string | null;
  hasHistory?: boolean;
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
  const locked = useRef(false);
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

  // The browser's start choices follow what the user set up: a draft, or a
  // change made in a conversation. Opening an older conversation only reads
  // its saved choices and leaves the draft alone.
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

  function load() {
    if (locked.current) return Promise.resolve();
    locked.current = true;
    const draft = !sessionId.current;
    return readSettings()
      .then(
        (next) => {
          install(next);
          if (draft) remember(next);
          if (mounted.current) setError(null);
        },
        (cause: unknown) => {
          if (mounted.current) setError(cause);
        }
      )
      .finally(() => {
        locked.current = false;
        if (mounted.current) setBusy(false);
      });
  }

  async function reload() {
    if (locked.current) return;
    setBusy(true);
    await load();
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

  async function update(patch: Partial<Settings>) {
    if (
      locked.current ||
      running ||
      !current.current ||
      current.current.settings_compatible === false
    )
      return;
    locked.current = true;
    setBusy(true);
    setError(null);
    const settings = { ...current.current.settings, ...patch };
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
      const next = await resolve(settings);
      install(next);
      remember(next);
    } catch (cause) {
      if (mounted.current) setError(cause);
    } finally {
      locked.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  function adoptSession(id: string, state: State | null | undefined) {
    sessionId.current = id;
    setHasMessages(true);
    if (state && current.current) install({ ...current.current, ...state });
    else void reload();
  }

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
        update,
        adoptSession
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
