"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useSpace } from "@/features/spaces/use-space";
import { isMcpEnforced, lockedAssistantModel, policyMcpServers } from "./effective-config";
import {
  assistantMcpServersFromApi,
  availableAssistantMcpServers,
  enabledMcpToolCount,
  isMcpToolEnabled,
  selectedMcpServers,
  setMcpServerToolsEnabled,
  toggleMcpServerSelection,
  toggleMcpToolSelection,
  type AssistantMcpServer,
  type AssistantMcpToolSetting
} from "./mcp-tool-selection";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

const sortedKey = (ids: Iterable<string>) => JSON.stringify([...ids].sort());
const sortedToolKey = (settings: AssistantMcpToolSetting[]) =>
  JSON.stringify([...settings].sort((a, b) => a.tool_id.localeCompare(b.tool_id)));

/**
 * MCP server picker. MCP servers and knowledge are mutually exclusive: when the
 * assistant already has knowledge attached and no MCP server selected, the
 * picker is disabled (the KnowledgeSection enforces the reciprocal rule). Only
 * shown when the space has MCP servers available.
 */
export function McpSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("mcp");

  const mcpEnforced = isMcpEnforced(assistant.effective_config);
  const policyServers = policyMcpServers(assistant.effective_config);
  const available = availableAssistantMcpServers(
    assistantMcpServersFromApi(mcpEnforced ? policyServers : (space.mcp_servers ?? []))
  );
  const savedIds = useMemo(
    () => (assistant.mcp_servers ?? []).map((server) => server.id),
    [assistant.mcp_servers]
  );
  const savedToolSettings = useMemo(() => assistant.mcp_tools ?? [], [assistant.mcp_tools]);
  const [selected, setSelected] = useState<Set<string>>(new Set(savedIds));
  const [toolSettings, setToolSettings] = useState<AssistantMcpToolSetting[]>(savedToolSettings);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const lockedModel = lockedAssistantModel(space.completion_models, assistant.effective_config);
  const selectedModel = lockedModel
    ? (space.completion_models.find((model) => model.id === lockedModel.id) ?? null)
    : (space.completion_models.find((model) => model.id === assistant.completion_model?.id) ??
      assistant.completion_model ??
      null);
  const modelSupportsTools = selectedModel?.supports_tool_calling !== false;

  // Adopt server changes (e.g. our own save landing) unless the user diverged.
  const savedKey = JSON.stringify([sortedKey(savedIds), sortedToolKey(savedToolSettings)]);
  const savedRef = useRef(savedKey);
  useEffect(() => {
    if (savedRef.current === savedKey) return;
    const previous = savedRef.current;
    savedRef.current = savedKey;
    const currentKey = JSON.stringify([sortedKey(selected), sortedToolKey(toolSettings)]);
    if (currentKey === previous) {
      setSelected(new Set(savedIds));
      setToolSettings(savedToolSettings);
    }
  }, [savedKey, savedIds, savedToolSettings, selected, toolSettings]);

  const hasKnowledge =
    assistant.groups.length +
      assistant.websites.length +
      assistant.integration_knowledge_list.length >
    0;
  const disabledByKnowledge = hasKnowledge && selected.size === 0;

  if (!mcpEnforced && available.length === 0) return null;

  function persist(
    nextSelected: Set<string>,
    nextToolSettings: AssistantMcpToolSetting[],
    previousSelected = selected,
    previousToolSettings = toolSettings
  ) {
    const attemptedSelectedKey = sortedKey(nextSelected);
    const attemptedToolKey = sortedToolKey(nextToolSettings);
    void autosave(() =>
      update.mutateAsync({
        mcp_servers: [...nextSelected].map((serverId) => ({ id: serverId })),
        mcp_tools: nextToolSettings
      })
    ).then((result) => {
      if (result !== undefined) return;
      setSelected((current) =>
        sortedKey(current) === attemptedSelectedKey ? previousSelected : current
      );
      setToolSettings((current) =>
        sortedToolKey(current) === attemptedToolKey ? previousToolSettings : current
      );
    });
  }

  function toggleServer(server: AssistantMcpServer) {
    const previousSelected = selected;
    const previousToolSettings = toolSettings;
    const next = toggleMcpServerSelection(selected, toolSettings, server);
    setSelected(next.selectedIds);
    setToolSettings(next.settings);
    persist(next.selectedIds, next.settings, previousSelected, previousToolSettings);
  }

  function updateToolSettings(nextToolSettings: AssistantMcpToolSetting[]) {
    const previousToolSettings = toolSettings;
    setToolSettings(nextToolSettings);
    persist(selected, nextToolSettings, selected, previousToolSettings);
  }

  const selectedServers = selectedMcpServers(available, selected);

  return (
    <SettingsGroup title={t("mcp_servers")} description={t("mcp_servers_description")}>
      <SettingsRow>
        <div className="flex flex-col gap-2">
          {!modelSupportsTools && (
            <p className="border-warning/30 bg-warning/10 text-warning rounded-md border px-3 py-2 text-sm">
              <span className="font-semibold">{t("warning")}:</span>{" "}
              {t("model_does_not_support_tools")}
            </p>
          )}
          {disabledByKnowledge && (
            <p className="border-warning/30 bg-warning/10 text-warning rounded-md border px-3 py-2 text-sm">
              <span className="font-semibold">{t("warning")}:</span>{" "}
              {t("mcp_disabled_when_knowledge_active")}
            </p>
          )}
          {mcpEnforced ? (
            <>
              {policyServers.length > 0 ? (
                <div className="divide-border divide-y rounded-lg border">
                  {policyServers.map((server) => (
                    <div key={server.id} className="flex flex-col gap-0.5 px-3 py-2">
                      <p className="text-sm font-medium">{server.name}</p>
                      {server.description && (
                        <p className="text-muted-foreground line-clamp-1 text-xs">
                          {server.description}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  {t("governance_assistant_mcp_none")}
                </p>
              )}
              <p className="text-muted-foreground text-xs">
                {t("governance_assistant_mcp_provided_by_policy")}
              </p>
            </>
          ) : (
            <fieldset
              className="flex flex-col gap-2"
              disabled={disabledByKnowledge}
              aria-label={t("mcp_servers")}
            >
              {available.map((server) => (
                <McpServerRow
                  key={server.id}
                  server={server}
                  selected={selected.has(server.id)}
                  expanded={expanded.has(server.id)}
                  disabled={disabledByKnowledge}
                  toolSettings={toolSettings}
                  onToggleServer={() => toggleServer(server)}
                  onToggleExpanded={() =>
                    setExpanded((current) => {
                      const next = new Set(current);
                      if (next.has(server.id)) next.delete(server.id);
                      else next.add(server.id);
                      return next;
                    })
                  }
                  onToggleTool={(toolId) =>
                    updateToolSettings(
                      toggleMcpToolSelection(selectedServers, toolSettings, toolId)
                    )
                  }
                  onSetAllTools={(isEnabled) =>
                    updateToolSettings(
                      setMcpServerToolsEnabled(selectedServers, toolSettings, server, isEnabled)
                    )
                  }
                />
              ))}
            </fieldset>
          )}
        </div>
      </SettingsRow>
    </SettingsGroup>
  );
}

function McpServerRow({
  server,
  selected,
  expanded,
  disabled,
  toolSettings,
  onToggleServer,
  onToggleExpanded,
  onToggleTool,
  onSetAllTools
}: {
  server: AssistantMcpServer;
  selected: boolean;
  expanded: boolean;
  disabled: boolean;
  toolSettings: AssistantMcpToolSetting[];
  onToggleServer: () => void;
  onToggleExpanded: () => void;
  onToggleTool: (toolId: string) => void;
  onSetAllTools: (isEnabled: boolean) => void;
}) {
  const t = useTranslations();
  const tools = server.tools ?? [];
  const hasTools = selected && tools.length > 0;
  const enabledToolCount = enabledMcpToolCount(server, toolSettings);

  return (
    <div className="border-border overflow-hidden rounded-lg border">
      <div className="flex items-center gap-1 p-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8 shrink-0"
          disabled={!hasTools || disabled}
          aria-label={t("mcp_tools_for_server_aria", { name: server.name })}
          aria-expanded={expanded}
          onClick={onToggleExpanded}
        >
          <ChevronRight
            aria-hidden="true"
            className={
              expanded ? "size-4 rotate-90 transition-transform" : "size-4 transition-transform"
            }
          />
        </Button>
        <Label className="flex min-w-0 flex-1 items-center justify-between gap-3 font-normal">
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="flex items-center gap-2">
              <span className="font-medium">{server.name}</span>
              {hasTools && (
                <span className="bg-secondary text-muted-foreground rounded px-1.5 py-0.5 text-[10px] font-medium tabular-nums">
                  <span>{enabledToolCount}</span>
                  <span className="px-0.5">/</span>
                  <span>{tools.length}</span>
                </span>
              )}
            </span>
            {server.description && (
              <span className="text-muted-foreground line-clamp-1 text-xs">
                {server.description}
              </span>
            )}
          </span>
          <Switch checked={selected} disabled={disabled} onCheckedChange={onToggleServer} />
        </Label>
      </div>

      {hasTools && expanded && (
        <div
          className="border-border bg-muted/30 mx-3 mb-3 rounded-md border"
          role="group"
          aria-label={t("mcp_tools_for_server_aria", { name: server.name })}
        >
          <div className="border-border flex items-center justify-between gap-2 border-b px-3 py-1.5">
            <span className="text-muted-foreground text-[11px] font-medium tracking-wider uppercase">
              {t("tools")} ({tools.length})
            </span>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => onSetAllTools(true)}
              >
                {t("mcp_all_on")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => onSetAllTools(false)}
              >
                {t("mcp_all_off")}
              </Button>
            </div>
          </div>
          <div className="max-h-60 overflow-y-auto">
            {tools.map((tool) => {
              const toolEnabled = isMcpToolEnabled(server, tool.id, toolSettings);
              return (
                <Label
                  key={tool.id}
                  className="hover:bg-muted/70 flex items-center gap-3 border-b px-3 py-2.5 font-normal last:border-b-0"
                >
                  <span className={toolEnabled ? "min-w-0 flex-1" : "min-w-0 flex-1 opacity-50"}>
                    <span className="block truncate font-mono text-xs font-medium">
                      {tool.title ?? tool.name}
                    </span>
                    {tool.description && (
                      <span className="text-muted-foreground line-clamp-1 text-xs">
                        {tool.description}
                      </span>
                    )}
                  </span>
                  <Switch checked={toolEnabled} onCheckedChange={() => onToggleTool(tool.id)} />
                </Label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
