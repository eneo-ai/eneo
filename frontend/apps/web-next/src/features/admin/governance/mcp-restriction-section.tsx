"use client";

import { AlertCircle, ChevronRight, Info, Plug } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { PolicySection } from "./policy-section";
import type { PolicyDraft } from "./use-policy-draft";

export function McpRestrictionSection({ draft }: { draft: PolicyDraft }) {
  const t = useTranslations();
  const {
    mcpEnabled,
    setMcpEnabled,
    allMcpServers,
    mcpSelections,
    disabledMcpToolIds,
    mcpSummary,
    mcpValid,
    badgeVariant,
    toggleMcp,
    toggleMcpDefault,
    toggleMcpTool
  } = draft;

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleExpanded = (serverId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(serverId)) next.delete(serverId);
      else next.add(serverId);
      return next;
    });

  return (
    <PolicySection
      id="mcp"
      title={t("governance_mcp_heading")}
      description={t("governance_mcp_section_desc")}
      summary={mcpSummary}
      summaryVariant={badgeVariant(mcpEnabled, mcpValid)}
      icon={<Plug className="size-5" />}
    >
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor="mcp-enabled" className="text-sm font-medium">
          {t("governance_mcp_toggle_label")}
        </Label>
        <Switch
          id="mcp-enabled"
          checked={mcpEnabled}
          onCheckedChange={setMcpEnabled}
          aria-describedby="mcp-help"
        />
      </div>

      {!mcpEnabled ? (
        <p id="mcp-help" className="text-muted-foreground text-sm">
          {t("governance_mcp_help_disabled")}
        </p>
      ) : allMcpServers.length === 0 ? (
        <p id="mcp-help" className="text-muted-foreground flex items-center gap-2 text-sm">
          <Info className="size-4 shrink-0" aria-hidden="true" />
          {t("governance_mcp_none_enabled")}
        </p>
      ) : (
        <>
          <p id="mcp-help" className="text-muted-foreground text-sm">
            {t("governance_mcp_help_enabled")}
          </p>
          <fieldset className="divide-border divide-y overflow-hidden rounded-lg border">
            <legend className="sr-only">{t("governance_mcp_legend")}</legend>
            {allMcpServers.map((server) => {
              const tools = server.tools ?? [];
              const isSelected = Boolean(mcpSelections[server.id]);
              const isDefaultEnabled = mcpSelections[server.id]?.isDefaultEnabled ?? true;
              const hasTools = tools.length > 0;
              const isExpanded = isSelected && expanded.has(server.id);
              const enabledCount = tools.filter((tool) => !disabledMcpToolIds.has(tool.id)).length;
              return (
                <div key={server.id} className={isSelected ? "bg-muted/40" : ""}>
                  <div className="flex items-center gap-3 py-2.5 pr-4 pl-1">
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground disabled:hover:text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md disabled:opacity-20"
                      disabled={!isSelected || !hasTools}
                      onClick={() => toggleExpanded(server.id)}
                      aria-label={
                        isExpanded ? t("governance_mcp_hide_tools") : t("governance_mcp_show_tools")
                      }
                      aria-expanded={isExpanded}
                    >
                      <ChevronRight
                        className={`size-4 transition-transform duration-200 ${isExpanded ? "rotate-90" : ""}`}
                      />
                    </button>
                    <Switch
                      checked={isSelected}
                      onCheckedChange={(value) => toggleMcp(server.id, value)}
                      aria-label={t("governance_mcp_allow_aria", { name: server.name })}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-sm font-medium ${isSelected ? "" : "text-muted-foreground"}`}
                        >
                          {server.name}
                        </span>
                        {isSelected && hasTools && (
                          <span className="bg-muted text-muted-foreground inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium tabular-nums">
                            {enabledCount}
                            <span className="text-muted-foreground">/</span>
                            {tools.length}
                          </span>
                        )}
                      </div>
                      {server.description && (
                        <p className="text-muted-foreground line-clamp-1 text-xs">
                          {server.description}
                        </p>
                      )}
                    </div>
                    {isSelected && (
                      <label className="flex shrink-0 items-center gap-2">
                        <span className="text-muted-foreground text-xs">
                          {t("governance_mcp_default_label")}
                        </span>
                        <Switch
                          checked={isDefaultEnabled}
                          onCheckedChange={(value) => toggleMcpDefault(server.id, value)}
                          aria-label={t("governance_mcp_default_aria", { name: server.name })}
                        />
                      </label>
                    )}
                  </div>

                  {isExpanded && (
                    <div
                      className="bg-muted/40 mr-3 mb-2.5 ml-9 rounded-lg border"
                      role="group"
                      aria-label={t("mcp_tools_for_server_aria", { name: server.name })}
                    >
                      <div className="flex items-center justify-between gap-3 border-b px-3 py-1.5">
                        <span className="text-muted-foreground text-[11px] font-medium tracking-wider uppercase">
                          {t("tools")} ({tools.length})
                        </span>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            className="text-muted-foreground hover:text-foreground hover:bg-accent rounded px-2 py-1 text-[10px] font-medium disabled:pointer-events-none disabled:opacity-40"
                            disabled={enabledCount === tools.length}
                            onClick={() => tools.forEach((tool) => toggleMcpTool(tool.id, true))}
                          >
                            {t("mcp_all_on")}
                          </button>
                          <span className="text-muted-foreground" aria-hidden="true">
                            |
                          </span>
                          <button
                            type="button"
                            className="text-muted-foreground hover:text-foreground hover:bg-accent rounded px-2 py-1 text-[10px] font-medium disabled:pointer-events-none disabled:opacity-40"
                            disabled={enabledCount === 0}
                            onClick={() => tools.forEach((tool) => toggleMcpTool(tool.id, false))}
                          >
                            {t("mcp_all_off")}
                          </button>
                        </div>
                      </div>
                      <div className="divide-border max-h-[240px] divide-y overflow-y-auto">
                        {tools.map((tool) => {
                          const toolEnabled = !disabledMcpToolIds.has(tool.id);
                          return (
                            <label
                              key={tool.id}
                              className={`hover:bg-accent flex items-center gap-3 px-3 py-2 ${toolEnabled ? "" : "opacity-50"}`}
                            >
                              <span className="min-w-0 flex-1">
                                <span className="block truncate font-mono text-xs font-medium">
                                  {tool.name}
                                </span>
                                {tool.description && (
                                  <span
                                    className="text-muted-foreground block truncate text-xs"
                                    title={tool.description}
                                  >
                                    {tool.description}
                                  </span>
                                )}
                              </span>
                              <Switch
                                checked={toolEnabled}
                                onCheckedChange={(value) => toggleMcpTool(tool.id, value)}
                                aria-label={tool.name}
                              />
                            </label>
                          );
                        })}
                      </div>
                      <p className="text-muted-foreground border-t px-3 py-1.5 text-xs">
                        {t("governance_mcp_tools_disabled_note")}
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </fieldset>
          {!mcpValid && (
            <p className="text-destructive flex items-center gap-2 text-sm" role="alert">
              <AlertCircle className="size-4 shrink-0" aria-hidden="true" />
              {t("governance_mcp_error_none")}
            </p>
          )}
        </>
      )}
    </PolicySection>
  );
}
