"use client";

import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery
} from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { PageHeader } from "@/components/composites/page-header";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { promptLibraryQueryOptions } from "@/features/admin/prompt-library/prompt-library-page";

type GovernancePolicy = Schema<"GovernancePolicyPublic">;
type GovernancePolicyUpdate = Schema<"GovernancePolicyUpdate">;

const POLICY_KEY = ["admin-governance-policy"];
const NO_PROMPT = "__none";

export function governancePolicyQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: POLICY_KEY,
    queryFn: (): Promise<GovernancePolicy> => unwrap(api.GET("/api/v1/admin/governance-policy/"))
  });
}

/** Map the current policy back into the update payload so a single-field edit preserves the rest. */
function toUpdate(policy: GovernancePolicy): GovernancePolicyUpdate {
  return {
    models_restriction: {
      enabled: policy.models_restriction.enabled,
      models: policy.models_restriction.models.map((model) => ({
        completion_model_id: model.completion_model_id,
        is_default: model.is_default
      })),
      provider_ids: policy.models_restriction.provider_ids
    },
    mcp_restriction: {
      enabled: policy.mcp_restriction.enabled,
      servers: policy.mcp_restriction.servers.map((server) => ({
        mcp_server_id: server.mcp_server_id
      })),
      disabled_tool_ids: policy.mcp_restriction.disabled_tool_ids
    },
    prompt_enforcement: {
      enabled: policy.prompt_enforcement.enabled,
      prompt_library_id: policy.prompt_enforcement.prompt_library_id
    }
  };
}

/**
 * Personal-assistant governance policy. Enable/disable the three restrictions
 * (preserving their allow-lists) and pick the enforced prompt. Editing the
 * model / MCP-server / tool allow-lists themselves is deferred (the Svelte
 * multi-section PolicyDraft) — tracked in the ledger.
 */
export function GovernancePolicyPage() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data: policy } = useSuspenseQuery(governancePolicyQueryOptions(browserApi));
  const { data: prompts = [] } = useQuery(promptLibraryQueryOptions(browserApi));

  const save = useMutation({
    mutationFn: (update: GovernancePolicyUpdate) =>
      unwrap(browserApi.PUT("/api/v1/admin/governance-policy/", { body: update })),
    onSuccess: (updated) => {
      queryClient.setQueryData(POLICY_KEY, updated);
      toast.success(t("governance_policy_saved"));
    },
    onError: (error) => toastApiError(error, t)
  });

  const update = (patch: Partial<GovernancePolicyUpdate>) =>
    save.mutate({ ...toUpdate(policy), ...patch });

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("governance_title")} />

      <SettingsGroup title={t("governance_models_restriction")}>
        <SettingsRow
          title={t("governance_restriction_enabled")}
          description={t("governance_models_restriction_hint")}
        >
          <Switch
            checked={policy.models_restriction.enabled}
            disabled={save.isPending}
            onCheckedChange={(enabled) =>
              update({
                models_restriction: { ...toUpdate(policy).models_restriction!, enabled }
              })
            }
          />
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title={t("governance_mcp_restriction")}>
        <SettingsRow
          title={t("governance_restriction_enabled")}
          description={t("governance_mcp_restriction_hint")}
        >
          <Switch
            checked={policy.mcp_restriction.enabled}
            disabled={save.isPending}
            onCheckedChange={(enabled) =>
              update({ mcp_restriction: { ...toUpdate(policy).mcp_restriction!, enabled } })
            }
          />
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title={t("governance_prompt_enforcement")}>
        <SettingsRow
          title={t("governance_enforcement_enabled")}
          description={t("governance_prompt_enforcement_hint")}
        >
          <Switch
            checked={policy.prompt_enforcement.enabled}
            disabled={save.isPending}
            onCheckedChange={(enabled) =>
              update({
                prompt_enforcement: { ...toUpdate(policy).prompt_enforcement!, enabled }
              })
            }
          />
        </SettingsRow>
        {policy.prompt_enforcement.enabled && (
          <SettingsRow title={t("governance_tab_prompts")} description={t("prompt")}>
            <Label htmlFor="governance-prompt" className="sr-only">
              {t("governance_tab_prompts")}
            </Label>
            <Select
              value={policy.prompt_enforcement.prompt_library_id ?? NO_PROMPT}
              disabled={save.isPending}
              onValueChange={(value) =>
                update({
                  prompt_enforcement: {
                    enabled: true,
                    prompt_library_id: value === NO_PROMPT ? null : value
                  }
                })
              }
            >
              <SelectTrigger className="w-full" id="governance-prompt">
                <SelectValue placeholder={t("governance_prompt_create")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_PROMPT}>{t("none")}</SelectItem>
                {prompts.map((prompt) => (
                  <SelectItem key={prompt.id} value={prompt.id}>
                    {prompt.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </SettingsRow>
        )}
      </SettingsGroup>
    </div>
  );
}
