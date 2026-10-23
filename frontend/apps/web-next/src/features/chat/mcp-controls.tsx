"use client";

import { Button } from "@astryxdesign/core/Button";
import { Popover } from "@astryxdesign/core/Popover";
import { Switch } from "@/components/astryx/switch";
import { Plug, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { CAPABILITIES, readinessKey, type Capability } from "@/features/capabilities/capabilities";
import type { Schema } from "@/lib/api/models";
import type { ChatPartner, ConversationBody } from "@/lib/chat/types";
import type { ChatCapability } from "./chat-capabilities";

export type McpServerSummary = Pick<
  Schema<"MCPServerPublicDict">,
  "id" | "name" | "description" | "icon_url"
> & { is_enabled?: boolean };

/**
 * Why a server cannot be used in this conversation, or null. An administrator
 * deactivating it is the more specific reason; otherwise a model without tool
 * calling makes every server unavailable, since the backend attaches none.
 */
export function mcpServerUnavailableReason(
  server: McpServerSummary,
  modelSupportsTools: boolean
): "server_disabled" | "model_no_tool_calling" | null {
  if (server.is_enabled === false) return "server_disabled";
  return modelSupportsTools ? null : "model_no_tool_calling";
}

export function chatPartnerMcpServers(partner: ChatPartner): McpServerSummary[] {
  if (partner.effectiveConfig?.mcp_enforced) {
    return (partner.effectiveConfig.available_mcp_servers ?? []).filter(
      (server) => server.purpose === "general"
    );
  }
  return (partner.mcpServers ?? []).filter((server) => server.purpose === "general");
}

export function defaultDisabledMcpServerIds(partner: ChatPartner): string[] {
  return partner.effectiveConfig?.default_disabled_mcp_server_ids ?? [];
}

export function pruneDisabledMcpServerIds(
  disabledServerIds: Set<string>,
  servers: McpServerSummary[]
): Set<string> {
  const validIds = new Set(servers.map((server) => server.id));
  return new Set([...disabledServerIds].filter((id) => validIds.has(id)));
}

/** Capabilities that will be offered: switched on and available. */
export function activeCapabilityCount(
  capabilities: ChatCapability[],
  disabledCapabilities: Set<Capability>
): number {
  return capabilities.filter(
    (capability) => capability.available && !disabledCapabilities.has(capability.purpose)
  ).length;
}

/** Servers that will be called: switched on and available (an unavailable server is off regardless). */
export function activeMcpServerCount(
  servers: McpServerSummary[],
  disabledServerIds: Set<string>,
  modelSupportsTools = true
): number {
  return servers.filter(
    (server) =>
      !disabledServerIds.has(server.id) &&
      mcpServerUnavailableReason(server, modelSupportsTools) === null
  ).length;
}

export function mcpConversationOptions({
  servers,
  disabledServerIds,
  autoAcceptTools,
  supportsToolApproval
}: {
  servers: McpServerSummary[];
  disabledServerIds: Set<string>;
  autoAcceptTools: boolean;
  supportsToolApproval: boolean;
}): Pick<ConversationBody, "require_tool_approval" | "disabled_mcp_server_ids"> {
  const disabledIds = [...disabledServerIds].filter((id) =>
    servers.some((server) => server.id === id)
  );
  return {
    require_tool_approval:
      supportsToolApproval && servers.length > 0 && !autoAcceptTools ? true : undefined,
    disabled_mcp_server_ids: disabledIds.length > 0 ? disabledIds : undefined
  };
}

const ROW_CLASS = "flex items-center gap-2.5 py-1.5";
const ROW_ICON_CLASS =
  "bg-ax-muted text-ax-text-secondary rounded-ax-inner flex size-7 shrink-0 items-center justify-center overflow-hidden text-xs font-semibold";

function ToolGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 py-1">
      <p className="text-ax-text-secondary text-xs font-semibold">{title}</p>
      <ul aria-label={title} className="flex flex-col">
        {children}
      </ul>
    </div>
  );
}

/**
 * The composer's Verktyg pill: a popover with a switch per capability (web
 * search, image generation, …) and per MCP server, all on / all off, plus
 * whether tools run without asking for approval. One control however many
 * functions the tenant offers: the pill carries the count of what is on.
 * When the partner's model cannot call tools, the backend attaches nothing:
 * every row is then rendered unavailable and the run-automatically choice is
 * hidden, since there is no tool call for it to govern.
 */
export function ChatTools({
  capabilities = [],
  disabledCapabilities = new Set(),
  servers = [],
  disabledServerIds = new Set(),
  autoAcceptTools,
  modelSupportsTools = true,
  onDisabledCapabilitiesChange,
  onDisabledServerIdsChange,
  onAutoAcceptToolsChange
}: {
  capabilities?: ChatCapability[];
  disabledCapabilities?: Set<Capability>;
  servers?: McpServerSummary[];
  disabledServerIds?: Set<string>;
  autoAcceptTools: boolean;
  /** Whether the partner's model can call tools at all; false renders every row unavailable. */
  modelSupportsTools?: boolean;
  onDisabledCapabilitiesChange?: (next: Set<Capability>) => void;
  onDisabledServerIdsChange?: (next: Set<string>) => void;
  onAutoAcceptToolsChange: (next: boolean) => void;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const total = capabilities.length + servers.length;
  const activeCount =
    activeCapabilityCount(capabilities, disabledCapabilities) +
    activeMcpServerCount(servers, disabledServerIds, modelSupportsTools);
  const activeLabel = t("mcp_servers_active_count", { active: activeCount, total });

  function setCapability(purpose: Capability, enabled: boolean) {
    const next = new Set(disabledCapabilities);
    if (enabled) next.delete(purpose);
    else next.add(purpose);
    onDisabledCapabilitiesChange?.(next);
  }

  function setServer(id: string, enabled: boolean) {
    const next = new Set(disabledServerIds);
    if (enabled) next.delete(id);
    else next.add(id);
    onDisabledServerIdsChange?.(next);
  }

  // All-on / all-off only sweeps the rows that can be used.
  function setAll(enabled: boolean) {
    if (capabilities.length > 0) {
      const next = new Set(disabledCapabilities);
      for (const capability of capabilities) {
        if (!capability.available) continue;
        if (enabled) next.delete(capability.purpose);
        else next.add(capability.purpose);
      }
      onDisabledCapabilitiesChange?.(next);
    }
    if (servers.length > 0) {
      const next = new Set(disabledServerIds);
      for (const server of servers) {
        if (mcpServerUnavailableReason(server, modelSupportsTools) !== null) continue;
        if (enabled) next.delete(server.id);
        else next.add(server.id);
      }
      onDisabledServerIdsChange?.(next);
    }
  }

  if (total === 0) return null;

  return (
    <Popover
      isOpen={open}
      onOpenChange={setOpen}
      placement="above"
      alignment="start"
      width={320}
      label={t("chat_tools")}
      closeButtonLabel={t("close")}
      content={
        <div className="flex flex-col">
          <div className="border-ax-border flex flex-col gap-1 border-b pb-2">
            <p className="text-sm font-semibold">{t("chat_tools")}</p>
            <div className="text-ax-text-secondary flex items-center justify-between gap-2 text-xs">
              <span>{activeLabel}</span>
              {total > 1 && modelSupportsTools && (
                // Never disabled: a button that disables itself when pressed
                // would drop keyboard focus. Pressing it again changes nothing.
                <span className="flex items-center gap-1">
                  <Button
                    label={t("mcp_all_on")}
                    variant="ghost"
                    size="sm"
                    onClick={() => setAll(true)}
                  />
                  <Button
                    label={t("mcp_all_off")}
                    variant="ghost"
                    size="sm"
                    onClick={() => setAll(false)}
                  />
                </span>
              )}
            </div>
            {!modelSupportsTools && (
              <p className="text-ax-warning text-xs">{t(readinessKey("model_no_tool_calling"))}</p>
            )}
          </div>

          <div className="flex max-h-72 flex-col overflow-y-auto">
            {capabilities.length > 0 && (
              <ToolGroup title={t("capabilities")}>
                {capabilities.map((capability) => {
                  const Icon = CAPABILITIES.find(
                    (item) => item.purpose === capability.purpose
                  )?.icon;
                  return (
                    <li key={capability.purpose} className={ROW_CLASS}>
                      <span aria-hidden="true" className={ROW_ICON_CLASS}>
                        {Icon ? <Icon className="size-4" /> : null}
                      </span>
                      <div className="min-w-0 flex-1">
                        {/* An unavailable capability is off whatever the switch
                            says; its reason replaces the description. */}
                        <Switch
                          label={t(capability.purpose)}
                          description={
                            capability.available ? undefined : t(readinessKey(capability.reason))
                          }
                          labelPosition="start"
                          labelSpacing="spread"
                          size="sm"
                          value={
                            capability.available && !disabledCapabilities.has(capability.purpose)
                          }
                          isDisabled={!capability.available}
                          onChange={(value) => setCapability(capability.purpose, value)}
                        />
                      </div>
                    </li>
                  );
                })}
              </ToolGroup>
            )}

            {servers.length > 0 && (
              <ToolGroup title={t("mcp_servers")}>
                {servers.map((server) => {
                  const reason = mcpServerUnavailableReason(server, modelSupportsTools);
                  return (
                    <li key={server.id} className={ROW_CLASS}>
                      <span aria-hidden="true" className={ROW_ICON_CLASS}>
                        {server.icon_url ? (
                          // Backend-served MCP icon URL.
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={server.icon_url} alt="" className="size-full object-cover" />
                        ) : (
                          server.name.charAt(0).toUpperCase()
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        {/* An unavailable server is off whatever the switch says: the
                            backend never calls it. The reason replaces the description. */}
                        <Switch
                          label={server.name}
                          description={
                            reason ? t(readinessKey(reason)) : (server.description ?? undefined)
                          }
                          labelPosition="start"
                          labelSpacing="spread"
                          size="sm"
                          value={reason === null && !disabledServerIds.has(server.id)}
                          isDisabled={reason !== null}
                          onChange={(value) => setServer(server.id, value)}
                        />
                      </div>
                    </li>
                  );
                })}
              </ToolGroup>
            )}
          </div>

          {modelSupportsTools && (
            <div className="border-ax-border flex items-start gap-2.5 border-t pt-2">
              <ShieldCheck
                aria-hidden="true"
                className="text-ax-text-secondary mt-0.5 size-5 shrink-0"
              />
              <div className="min-w-0 flex-1">
                <Switch
                  label={t("mcp_run_tools_automatically")}
                  description={
                    autoAcceptTools ? t("auto_accept_tools_on") : t("auto_accept_tools_off")
                  }
                  labelPosition="start"
                  labelSpacing="spread"
                  size="sm"
                  value={autoAcceptTools}
                  onChange={onAutoAcceptToolsChange}
                />
              </div>
            </div>
          )}
        </div>
      }
    >
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t("chat_tools_named", { status: activeLabel })}
        className="text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text focus-visible:outline-ring aria-expanded:bg-ax-hover inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11 pointer-coarse:min-w-11"
      >
        <Plug aria-hidden="true" className="size-[15px]" />
        <span className="max-sm:sr-only">{t("chat_tools")}</span>
        <span
          aria-hidden="true"
          className="bg-ax-muted text-ax-text flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1.5 text-[11px] tabular-nums"
        >
          {activeCount}
        </span>
      </button>
    </Popover>
  );
}
