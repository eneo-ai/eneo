"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useSpace } from "@/features/spaces/use-space";
import { SaveRow } from "./general-section";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

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

  const available = space.mcp_servers ?? [];
  const savedIds = (assistant.mcp_servers ?? []).map((server) => server.id);
  const [selected, setSelected] = useState<Set<string>>(new Set(savedIds));

  const dirty = JSON.stringify([...selected].sort()) !== JSON.stringify([...savedIds].sort());

  const hasKnowledge =
    assistant.groups.length +
      assistant.websites.length +
      assistant.integration_knowledge_list.length >
    0;
  const disabledByKnowledge = hasKnowledge && selected.size === 0;

  if (available.length === 0) return null;

  function toggle(id: string, on: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  return (
    <SettingsGroup title={t("mcp_servers")}>
      <SettingsRow title={t("mcp_servers")} description={t("mcp_servers_description")}>
        <div className="flex flex-col gap-2">
          {disabledByKnowledge && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
              <span className="font-semibold">{t("warning")}:</span>{" "}
              {t("mcp_disabled_when_knowledge_active")}
            </p>
          )}
          <fieldset
            className="flex flex-col gap-2"
            disabled={disabledByKnowledge}
            aria-label={t("mcp_servers")}
          >
            {available.map((server) => (
              <Label
                key={server.id}
                className="border-border flex items-center justify-between gap-3 rounded-lg border p-3 font-normal"
              >
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="font-medium">{server.name}</span>
                  {server.description && (
                    <span className="text-muted-foreground line-clamp-1 text-xs">
                      {server.description}
                    </span>
                  )}
                </span>
                <Switch
                  checked={selected.has(server.id)}
                  disabled={disabledByKnowledge}
                  onCheckedChange={(on) => toggle(server.id, on)}
                />
              </Label>
            ))}
          </fieldset>
        </div>
      </SettingsRow>
      <SaveRow
        dirty={dirty}
        pending={update.isPending}
        onSave={() => update.mutate({ mcp_servers: [...selected].map((id) => ({ id })) })}
        onRevert={() => setSelected(new Set(savedIds))}
      />
    </SettingsGroup>
  );
}
