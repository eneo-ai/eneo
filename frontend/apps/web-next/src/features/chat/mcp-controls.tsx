"use client";

import { Button } from "@astryxdesign/core/Button";
import { Popover } from "@astryxdesign/core/Popover";
import { Switch } from "@/components/astryx/switch";
import { Plug, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import type { Schema } from "@/lib/api/models";
import type { ChatPartner, ConversationBody } from "@/lib/chat/types";

export type McpServerSummary = Pick<
  Schema<"MCPServerPublicDict">,
  "id" | "name" | "description" | "icon_url"
>;

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

export function activeMcpServerCount(
  servers: McpServerSummary[],
  disabledServerIds: Set<string>
): number {
  return servers.filter((server) => !disabledServerIds.has(server.id)).length;
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

/**
 * The composer's Verktyg pill: a popover with a switch per MCP server (and
 * all on / all off), plus whether tools run without asking for approval.
 */
export function ChatMcpServers({
  servers,
  disabledServerIds,
  autoAcceptTools,
  onDisabledServerIdsChange,
  onAutoAcceptToolsChange
}: {
  servers: McpServerSummary[];
  disabledServerIds: Set<string>;
  autoAcceptTools: boolean;
  onDisabledServerIdsChange: (next: Set<string>) => void;
  onAutoAcceptToolsChange: (next: boolean) => void;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const total = servers.length;
  const activeCount = activeMcpServerCount(servers, disabledServerIds);
  const activeLabel = t("mcp_servers_active_count", { active: activeCount, total });

  function setServer(id: string, enabled: boolean) {
    const next = new Set(disabledServerIds);
    if (enabled) next.delete(id);
    else next.add(id);
    onDisabledServerIdsChange(next);
  }

  function setAll(enabled: boolean) {
    const next = new Set(disabledServerIds);
    for (const server of servers) {
      if (enabled) next.delete(server.id);
      else next.add(server.id);
    }
    onDisabledServerIdsChange(next);
  }

  if (servers.length === 0) return null;

  return (
    <Popover
      isOpen={open}
      onOpenChange={setOpen}
      placement="above"
      alignment="start"
      width={320}
      label={t("mcp_servers")}
      closeButtonLabel={t("close")}
      content={
        <div className="flex flex-col">
          <div className="border-ax-border flex flex-col gap-1 border-b pb-2">
            <p className="text-sm font-semibold">{t("mcp_servers")}</p>
            <div className="text-ax-text-secondary flex items-center justify-between gap-2 text-xs">
              <span>{activeLabel}</span>
              {total > 1 && (
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
          </div>

          <ul aria-label={t("mcp_servers")} className="flex max-h-64 flex-col overflow-y-auto py-1">
            {servers.map((server) => (
              <li key={server.id} className="flex items-center gap-2.5 py-1.5">
                <span
                  aria-hidden="true"
                  className="bg-ax-muted text-ax-text-secondary rounded-ax-inner flex size-7 shrink-0 items-center justify-center overflow-hidden text-xs font-semibold"
                >
                  {server.icon_url ? (
                    // Backend-served MCP icon URL.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={server.icon_url} alt="" className="size-full object-cover" />
                  ) : (
                    server.name.charAt(0).toUpperCase()
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <Switch
                    label={server.name}
                    description={server.description ?? undefined}
                    labelPosition="start"
                    labelSpacing="spread"
                    size="sm"
                    value={!disabledServerIds.has(server.id)}
                    onChange={(value) => setServer(server.id, value)}
                  />
                </div>
              </li>
            ))}
          </ul>

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
