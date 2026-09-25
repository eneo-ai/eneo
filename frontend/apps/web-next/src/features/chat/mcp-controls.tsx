"use client";

import { Plug, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
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
  const total = servers.length;
  const activeCount = activeMcpServerCount(servers, disabledServerIds);

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
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`${t("chat_tools")}: ${t("mcp_servers_active_count", { active: activeCount, total })}`}
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
      </PopoverTrigger>

      <PopoverContent side="top" align="start" className="w-80 gap-0 p-0">
        <div className="border-b px-3 py-2.5">
          <PopoverTitle className="text-sm">{t("mcp_servers")}</PopoverTitle>
          <div className="text-muted-foreground mt-0.5 flex items-center justify-between gap-2 text-xs">
            <span>{t("mcp_servers_active_count", { active: activeCount, total })}</span>
            {total > 1 && (
              <span className="flex items-center gap-0.5">
                <button
                  type="button"
                  className="hover:text-foreground rounded px-1 py-0.5 font-medium transition-colors disabled:pointer-events-none disabled:opacity-40"
                  disabled={activeCount === total}
                  onClick={() => setAll(true)}
                >
                  {t("mcp_all_on")}
                </button>
                <span aria-hidden="true" className="text-border">
                  ·
                </span>
                <button
                  type="button"
                  className="hover:text-foreground rounded px-1 py-0.5 font-medium transition-colors disabled:pointer-events-none disabled:opacity-40"
                  disabled={activeCount === 0}
                  onClick={() => setAll(false)}
                >
                  {t("mcp_all_off")}
                </button>
              </span>
            )}
          </div>
        </div>

        <div
          className="flex max-h-64 flex-col overflow-y-auto p-1"
          role="group"
          aria-label={t("mcp_servers")}
        >
          {servers.map((server) => {
            const enabled = !disabledServerIds.has(server.id);
            const descriptionId = server.description ? `mcp-desc-${server.id}` : undefined;
            return (
              <div
                key={server.id}
                className="hover:bg-muted flex items-center gap-2.5 rounded-md px-2 py-2 transition-colors"
              >
                <span
                  className="bg-ax-muted text-ax-text-secondary rounded-ax-inner flex size-7 shrink-0 items-center justify-center overflow-hidden text-xs font-semibold"
                  aria-hidden="true"
                >
                  {server.icon_url ? (
                    // Backend-served MCP icon URL.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={server.icon_url} alt="" className="size-full object-cover" />
                  ) : (
                    server.name.charAt(0).toUpperCase()
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={`block truncate text-sm font-medium ${enabled ? "text-ax-text" : "text-ax-text-secondary"}`}
                  >
                    {server.name}
                  </span>
                  {server.description && (
                    <span
                      id={descriptionId}
                      className="text-muted-foreground block truncate text-xs"
                      title={server.description}
                    >
                      {server.description}
                    </span>
                  )}
                </span>
                <Switch
                  checked={enabled}
                  onCheckedChange={(value) => setServer(server.id, value)}
                  aria-label={server.name}
                  aria-describedby={descriptionId}
                />
              </div>
            );
          })}
        </div>

        <Separator />

        <div className="p-1">
          <div className="hover:bg-muted flex items-start gap-2.5 rounded-md px-2 py-2 transition-colors">
            <ShieldCheck
              className="text-muted-foreground mt-0.5 size-5 shrink-0"
              aria-hidden="true"
            />
            <span className="min-w-0 flex-1">
              <span className="text-foreground block text-sm font-medium">
                {t("mcp_run_tools_automatically")}
              </span>
              <span id="mcp-auto-accept-desc" className="text-muted-foreground block text-xs">
                {autoAcceptTools ? t("auto_accept_tools_on") : t("auto_accept_tools_off")}
              </span>
            </span>
            <Switch
              checked={autoAcceptTools}
              onCheckedChange={onAutoAcceptToolsChange}
              aria-label={t("mcp_run_tools_automatically")}
              aria-describedby="mcp-auto-accept-desc"
            />
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
