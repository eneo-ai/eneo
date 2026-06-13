"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import { promptLibraryQueryOptions } from "@/features/admin/prompt-library/prompt-library";
import { governancePolicyQueryOptions, modelProvidersQueryOptions } from "./governance";
import { McpRestrictionSection } from "./mcp-restriction-section";
import { ModelRestrictionSection } from "./model-restriction-section";
import { PolicyConfirmDialog } from "./policy-confirm-dialog";
import { PolicySaveBar } from "./policy-save-bar";
import { PromptEnforcementSection } from "./prompt-enforcement-section";
import { usePolicyDraft } from "./use-policy-draft";

/**
 * Personal-assistant governance policy. Three independent restrictions for the
 * org-wide personal assistant: which completion models/providers are allowed
 * (and the single default), which MCP servers are available (with per-server
 * default state and per-tool enablement), and an optionally-enforced system
 * prompt. Edits accumulate against the saved baseline and apply atomically via
 * the save bar, with a confirm step for the irreversible-feeling changes.
 */
export function GovernancePolicyPage() {
  const t = useTranslations();
  const { data: policy } = useSuspenseQuery(governancePolicyQueryOptions(browserApi));
  const { data: models } = useSuspenseQuery(adminModelsQueryOptions(browserApi));
  const { data: providers } = useSuspenseQuery(modelProvidersQueryOptions(browserApi));
  const { data: servers } = useSuspenseQuery(mcpServersQueryOptions(browserApi));
  const { data: prompts } = useSuspenseQuery(promptLibraryQueryOptions(browserApi));

  const draft = usePolicyDraft({
    policy,
    models: models.completion_models,
    providers,
    servers,
    prompts
  });

  return (
    <>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 pb-32">
        <PageHeader title={t("governance_title")} />
        <ModelRestrictionSection draft={draft} />
        <McpRestrictionSection draft={draft} />
        <PromptEnforcementSection draft={draft} />
      </div>

      {/* Live region for save status (announced by screen readers) */}
      <div role="status" aria-live="polite" className="sr-only">
        {draft.saveAnnouncement}
      </div>

      <PolicySaveBar
        dirty={draft.dirty}
        saveError={draft.saveError}
        canSave={draft.canSave}
        saving={draft.saving}
        onDiscard={draft.discard}
        onSave={draft.save}
      />
      <PolicyConfirmDialog
        pending={draft.pendingConfirm}
        saving={draft.saving}
        onCancel={draft.cancelConfirm}
        onConfirm={draft.confirmSave}
      />
    </>
  );
}
