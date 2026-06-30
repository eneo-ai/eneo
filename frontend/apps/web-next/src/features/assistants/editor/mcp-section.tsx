"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useSpace } from "@/features/spaces/use-space";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

const sortedKey = (ids: Iterable<string>) => JSON.stringify([...ids].sort());

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

  const available = space.mcp_servers ?? [];
  const savedIds = (assistant.mcp_servers ?? []).map((server) => server.id);
  const [selected, setSelected] = useState<Set<string>>(new Set(savedIds));

  // Adopt server changes (e.g. our own save landing) unless the user diverged.
  const savedKey = sortedKey(savedIds);
  const savedRef = useRef(savedKey);
  useEffect(() => {
    if (savedRef.current === savedKey) return;
    const previous = savedRef.current;
    savedRef.current = savedKey;
    setSelected((current) => (sortedKey(current) === previous ? new Set(savedIds) : current));
  }, [savedKey, savedIds]);

  const hasKnowledge =
    assistant.groups.length +
      assistant.websites.length +
      assistant.integration_knowledge_list.length >
    0;
  const disabledByKnowledge = hasKnowledge && selected.size === 0;

  if (available.length === 0) return null;

  function toggle(id: string, on: boolean) {
    const next = new Set(selected);
    if (on) next.add(id);
    else next.delete(id);
    setSelected(next);
    void autosave(() => update.mutateAsync({ mcp_servers: [...next].map((id) => ({ id })) }));
  }

  return (
    <SettingsGroup title={t("mcp_servers")} description={t("mcp_servers_description")}>
      <SettingsRow>
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
    </SettingsGroup>
  );
}
