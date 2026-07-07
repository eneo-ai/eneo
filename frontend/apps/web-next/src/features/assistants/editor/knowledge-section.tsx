"use client";

import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { KnowledgePicker } from "@/features/knowledge/select/knowledge-picker";
import type { KnowledgeSelections } from "@/features/knowledge/select/logic";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

function toIds(selections: KnowledgeSelections): string {
  return JSON.stringify([
    selections.collections.map((item) => item.id).sort(),
    selections.websites.map((item) => item.id).sort(),
    selections.integrationKnowledge.map((item) => item.id).sort()
  ]);
}

/**
 * Personal + organization knowledge pickers. Knowledge and MCP servers are
 * mutually exclusive: when MCP servers are active and no knowledge exists the
 * pickers are disabled (legacy data with both stays editable so the user can
 * resolve the conflict). The MCP picker itself is a deferred follow-up.
 */
export function KnowledgeSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("knowledge");

  const saved: KnowledgeSelections = useMemo(
    () => ({
      collections: assistant.groups,
      websites: assistant.websites,
      integrationKnowledge: assistant.integration_knowledge_list
    }),
    [assistant.groups, assistant.websites, assistant.integration_knowledge_list]
  );
  const [selections, setSelections] = useState<KnowledgeSelections>(saved);

  // Adopt server changes (e.g. our own save landing) unless the user diverged.
  const savedKey = toIds(saved);
  const savedRef = useRef(savedKey);
  useEffect(() => {
    if (savedRef.current === savedKey) return;
    const previous = savedRef.current;
    savedRef.current = savedKey;
    setSelections((current) => (toIds(current) === previous ? saved : current));
  }, [savedKey, saved]);

  function handleChange(next: KnowledgeSelections) {
    const previous = selections;
    const attemptedKey = toIds(next);
    setSelections(next);
    void autosave(() =>
      update.mutateAsync({
        groups: next.collections.map((item) => ({ id: item.id })),
        websites: next.websites.map((item) => ({ id: item.id })),
        integration_knowledge_list: next.integrationKnowledge.map((item) => ({ id: item.id }))
      })
    ).then((result) => {
      if (result !== undefined) return;
      setSelections((current) => (toIds(current) === attemptedKey ? previous : current));
    });
  }

  const hasAnyKnowledge =
    selections.collections.length +
      selections.websites.length +
      selections.integrationKnowledge.length >
    0;
  const hasAnyMcp = (assistant.mcp_servers?.length ?? 0) > 0;
  const disabledByMcp = hasAnyMcp && !hasAnyKnowledge;

  const warning = disabledByMcp && (
    <p className="border-warning/30 bg-warning/10 text-warning rounded-md border px-3 py-2 text-sm">
      <span className="font-semibold">{t("warning")}:</span>{" "}
      {t("knowledge_disabled_when_mcp_active")}
    </p>
  );

  return (
    <SettingsGroup title={t("knowledge")}>
      <SettingsRow title={t("knowledge")} description={t("select_additional_knowledge")}>
        <div className="flex flex-col gap-2">
          {warning}
          <KnowledgePicker
            origin="personal"
            selections={selections}
            onChange={handleChange}
            disabled={disabledByMcp}
          />
        </div>
      </SettingsRow>
      <SettingsRow
        title={t("organization_knowledge")}
        description={t("organization_knowledge_description")}
      >
        <div className="flex flex-col gap-2">
          {warning}
          <KnowledgePicker
            origin="organization"
            selections={selections}
            onChange={handleChange}
            disabled={disabledByMcp}
          />
        </div>
      </SettingsRow>
    </SettingsGroup>
  );
}
