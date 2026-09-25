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

function storageKey(context: McpServerPreferencesContext): string {
  return `${STORAGE_PREFIX}${context.tenantId}:${context.userId}:${context.assistantId}`;
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

    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      !("serverStates" in parsed) ||
      typeof parsed.serverStates !== "object" ||
      parsed.serverStates === null ||
      Array.isArray(parsed.serverStates)
    ) {
      resolvedStorage.removeItem(storageKey(context));
      return null;
    }

    const serverStates: Record<string, boolean> = {};
    for (const [serverId, enabled] of Object.entries(parsed.serverStates)) {
      if (typeof enabled === "boolean") serverStates[serverId] = enabled;
    }

    return { serverStates };
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
