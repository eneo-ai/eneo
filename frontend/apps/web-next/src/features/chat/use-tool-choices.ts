"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useAppContext } from "@/components/providers/app-context";
import type { Capability } from "@/features/capabilities/capabilities";
import type { ChatPartner } from "@/lib/chat/types";
import { chatCapabilities, defaultDisabledCapabilities } from "./chat-capabilities";
import {
  chatPartnerMcpServers,
  defaultDisabledMcpServerIds,
  pruneDisabledMcpServerIds
} from "./mcp-controls";
import {
  initialDisabledMcpServerIds,
  parseMcpPreferences,
  readMcpPreferencesRaw,
  saveMcpServerPreferences,
  subscribeMcpPreferences
} from "./mcp-preferences";

const AUTO_ACCEPT_TOOLS_STORAGE_KEY = "autoAcceptToolsEnabled";

function autoAcceptToolsPreference(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(AUTO_ACCEPT_TOOLS_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

/**
 * The composer's tool choices for a partner: which capabilities (web search,
 * image generation) and MCP servers are on, and whether tools run without
 * approval. Governance defaults apply first; the personal assistant remembers
 * the user's choices per tenant, user and assistant (mcp-preferences.ts).
 */
export function useToolChoices(partner: ChatPartner) {
  const { featureFlags, tenant, user, can } = useAppContext();
  const allCapabilities = useMemo(() => chatCapabilities(partner, can), [partner, can]);
  const capabilities = allCapabilities.filter(
    (capability) => capability.purpose !== "web_search" || featureFlags.showWebSearch
  );
  const mcpServers = useMemo(() => chatPartnerMcpServers(partner), [partner]);
  const preferenceIds = useMemo(
    () => [
      ...mcpServers.map((server) => server.id),
      ...allCapabilities.map((capability) => `capability:${capability.purpose}`)
    ],
    [mcpServers, allCapabilities]
  );
  const preferenceContext = useMemo(
    () =>
      partner.type === "default-assistant"
        ? { tenantId: tenant.id, userId: user.id, assistantId: partner.id }
        : null,
    [partner.type, partner.id, tenant.id, user.id]
  );
  const readPreferenceSnapshot = useCallback(
    () => (preferenceContext ? readMcpPreferencesRaw(preferenceContext) : null),
    [preferenceContext]
  );
  const rawPreferences = useSyncExternalStore(
    subscribeMcpPreferences,
    readPreferenceSnapshot,
    () => null
  );
  const savedPreferences = useMemo(() => parseMcpPreferences(rawPreferences), [rawPreferences]);
  const defaultDisabledPreferenceIds = useMemo(
    () => [
      ...defaultDisabledMcpServerIds(partner),
      ...defaultDisabledCapabilities(partner).map((purpose) => `capability:${purpose}`)
    ],
    [partner]
  );
  const resolvedDisabledIds = useMemo(
    () =>
      initialDisabledMcpServerIds({
        availableServerIds: preferenceIds,
        defaultDisabledServerIds: defaultDisabledPreferenceIds,
        preferences: savedPreferences
      }),
    [preferenceIds, defaultDisabledPreferenceIds, savedPreferences]
  );

  const [autoAcceptTools, setAutoAcceptTools] = useState(autoAcceptToolsPreference);
  const [locallyEditedPreferences, setLocallyEditedPreferences] = useState(false);
  const [localDisabledCapabilities, setLocalDisabledCapabilities] = useState<Set<Capability>>(
    () => new Set(defaultDisabledCapabilities(partner))
  );
  const [localDisabledMcpServerIds, setLocalDisabledMcpServerIds] = useState<Set<string>>(
    () => new Set(defaultDisabledMcpServerIds(partner))
  );
  const disabledMcpServerIds = useMemo(
    () =>
      locallyEditedPreferences
        ? localDisabledMcpServerIds
        : new Set(resolvedDisabledIds.filter((id) => !id.startsWith("capability:"))),
    [locallyEditedPreferences, localDisabledMcpServerIds, resolvedDisabledIds]
  );
  const disabledCapabilities = locallyEditedPreferences
    ? localDisabledCapabilities
    : new Set(
        allCapabilities
          .filter((capability) => resolvedDisabledIds.includes(`capability:${capability.purpose}`))
          .map((capability) => capability.purpose)
      );

  function persistToolChoices(mcpDisabled: Set<string>, capabilityDisabled: Set<Capability>) {
    if (!preferenceContext) return;
    saveMcpServerPreferences(
      preferenceContext,
      preferenceIds,
      new Set([
        ...mcpDisabled,
        ...[...capabilityDisabled].map((purpose) => `capability:${purpose}`)
      ])
    );
  }

  function setCapabilityEnabled(purpose: Capability) {
    const next = new Set(disabledCapabilities);
    if (next.has(purpose)) next.delete(purpose);
    else next.add(purpose);
    setLocalDisabledCapabilities(next);
    setLocalDisabledMcpServerIds(disabledMcpServerIds);
    setLocallyEditedPreferences(true);
    persistToolChoices(disabledMcpServerIds, next);
  }

  function setMcpDisabled(next: Set<string>) {
    setLocalDisabledMcpServerIds(next);
    setLocalDisabledCapabilities(disabledCapabilities);
    setLocallyEditedPreferences(true);
    persistToolChoices(next, disabledCapabilities);
  }
  const activeDisabledMcpServerIds = useMemo(
    () => pruneDisabledMcpServerIds(disabledMcpServerIds, mcpServers),
    [disabledMcpServerIds, mcpServers]
  );
  useEffect(() => {
    try {
      window.localStorage.setItem(
        AUTO_ACCEPT_TOOLS_STORAGE_KEY,
        autoAcceptTools ? "true" : "false"
      );
    } catch {
      // Ignore preference persistence failures.
    }
  }, [autoAcceptTools]);

  return {
    /** Capabilities offered in the composer (web search only when the deployment shows it). */
    capabilities,
    disabledCapabilities,
    toggleCapability: setCapabilityEnabled,
    mcpServers,
    /** Disabled MCP servers among those the partner offers. */
    disabledMcpServerIds: activeDisabledMcpServerIds,
    setDisabledMcpServerIds: setMcpDisabled,
    autoAcceptTools,
    setAutoAcceptTools
  };
}
