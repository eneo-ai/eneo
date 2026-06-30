"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useReportDirty } from "@/components/composites/save-status";
import { KnowledgePicker } from "@/features/knowledge/select/knowledge-picker";
import type { KnowledgeSelections } from "@/features/knowledge/select/logic";
import { SaveRow } from "./general-section";
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

  const saved: KnowledgeSelections = {
    collections: assistant.groups,
    websites: assistant.websites,
    integrationKnowledge: assistant.integration_knowledge_list
  };
  const [selections, setSelections] = useState<KnowledgeSelections>(saved);

  const dirty = toIds(selections) !== toIds(saved);
  useReportDirty("knowledge", dirty);

  const hasAnyKnowledge =
    selections.collections.length +
      selections.websites.length +
      selections.integrationKnowledge.length >
    0;
  const hasAnyMcp = (assistant.mcp_servers?.length ?? 0) > 0;
  const disabledByMcp = hasAnyMcp && !hasAnyKnowledge;

  const warning = disabledByMcp && (
    <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
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
            onChange={setSelections}
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
            onChange={setSelections}
            disabled={disabledByMcp}
          />
        </div>
      </SettingsRow>
      <SaveRow
        dirty={dirty}
        pending={update.isPending}
        onSave={() =>
          update.mutate({
            groups: selections.collections.map((item) => ({ id: item.id })),
            websites: selections.websites.map((item) => ({ id: item.id })),
            integration_knowledge_list: selections.integrationKnowledge.map((item) => ({
              id: item.id
            }))
          })
        }
        onRevert={() => setSelections(saved)}
      />
    </SettingsGroup>
  );
}
