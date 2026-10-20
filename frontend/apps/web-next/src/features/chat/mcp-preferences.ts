const STORAGE_PREFIX = "eneo:chat-mcp:v1:";

export interface McpServerPreferencesContext {
  tenantId: string;
  userId: string;
  assistantId: string;
}

export interface McpServerPreferences {
  serverStates: Record<string, boolean>;
}

interface PreferencesStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export function storageKey(context: McpServerPreferencesContext): string {
  return `${STORAGE_PREFIX}${context.tenantId}:${context.userId}:${context.assistantId}`;
}

const listeners = new Set<() => void>();

export function subscribeMcpPreferences(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key?.startsWith(STORAGE_PREFIX)) listener();
  };
  if (typeof window !== "undefined") window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    if (typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
}

export function readMcpPreferencesRaw(context: McpServerPreferencesContext): string | null {
  try {
    return globalThis.localStorage.getItem(storageKey(context));
  } catch {
    return null;
  }
}

export function parseMcpPreferences(raw: string | null): McpServerPreferences | null {
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      !("serverStates" in parsed) ||
      typeof parsed.serverStates !== "object" ||
      parsed.serverStates === null ||
      Array.isArray(parsed.serverStates)
    )
      return null;
    const serverStates: Record<string, boolean> = {};
    for (const [serverId, enabled] of Object.entries(parsed.serverStates)) {
      if (typeof enabled === "boolean") serverStates[serverId] = enabled;
    }
    return { serverStates };
  } catch {
    return null;
  }
}

function resolveStorage(storage?: PreferencesStorage): PreferencesStorage {
  return storage ?? globalThis.localStorage;
}

export function loadMcpServerPreferences(
  context: McpServerPreferencesContext,
  storage?: PreferencesStorage
): McpServerPreferences | null {
  try {
    const resolvedStorage = resolveStorage(storage);
    const raw = resolvedStorage.getItem(storageKey(context));
    if (raw === null) return null;

    const preferences = parseMcpPreferences(raw);
    if (!preferences) {
      resolvedStorage.removeItem(storageKey(context));
      return null;
    }
    return preferences;
  } catch {
    return null;
  }
}

export function saveMcpServerPreferences(
  context: McpServerPreferencesContext,
  availableServerIds: readonly string[],
  disabledServerIds: ReadonlySet<string>,
  storage?: PreferencesStorage
): void {
  const serverStates = Object.fromEntries(
    availableServerIds.map((serverId) => [serverId, !disabledServerIds.has(serverId)])
  );

  try {
    resolveStorage(storage).setItem(storageKey(context), JSON.stringify({ serverStates }));
    for (const listener of listeners) listener();
  } catch {
    // A blocked or full localStorage must not prevent the user from chatting.
  }
}

export function initialDisabledMcpServerIds({
  availableServerIds,
  defaultDisabledServerIds,
  preferences
}: {
  availableServerIds: readonly string[];
  defaultDisabledServerIds: readonly string[];
  preferences: McpServerPreferences | null;
}): string[] {
  const defaultDisabled = new Set(defaultDisabledServerIds);

  return availableServerIds.filter((serverId) => {
    const persistedState = preferences?.serverStates[serverId];
    return persistedState === undefined ? defaultDisabled.has(serverId) : !persistedState;
  });
}
