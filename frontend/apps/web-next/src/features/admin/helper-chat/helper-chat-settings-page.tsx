import { useAnnounce } from "@astryxdesign/core/hooks";
import { Link } from "@astryxdesign/core/Link";
import { Switch } from "@astryxdesign/core/Switch";
import { Text } from "@astryxdesign/core/Text";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { FLOW_SETTINGS_KEY } from "@/features/admin/flow-settings/flow-settings";
import {
  adminModelsQueryOptions,
  toolCapableCompletionModels
} from "@/features/admin/models/models";
import { settingSwitchScope, useSettingSwitch } from "@/features/admin/use-setting-switch";
import { browserApi } from "@/lib/api/browser";
import {
  HELPER_CHAT_POLICY_KEY,
  HELPER_CHAT_POLICY_QUEUE,
  helperChatPolicyQueryOptions,
  modelRefusalMessage,
  updateHelperChatPolicy,
  type HelperChatPolicy
} from "./helper-chat-policy";
import { HelperGuidanceField } from "./helper-guidance-field";

/** Where the flow chat's own setting of the shared default model is. */
const FLOW_CHAT_SETTINGS_HREF = "/admin/flow-settings#flow-chat";

/**
 * The helper assistant's organisation settings: whether it is on, its default
 * model and the organisation's guidance. The switch and the model save as
 * they change; the guidance has its own Save.
 */
export function HelperChatSettingsPage() {
  const t = useTranslations();
  const policy = useQuery(helperChatPolicyQueryOptions(browserApi));
  return (
    <div className="flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("admin_helper_title")} description={t("admin_helper_description")} />
      <QueryStateBoundary query={policy} rows={6}>
        {(current) => (
          <>
            <EnabledSetting policy={current} />
            <DefaultModelSetting policy={current} />
            <HelperGuidanceField policy={current} />
          </>
        )}
      </QueryStateBoundary>
    </div>
  );
}

/** Saves on toggle (`useSettingSwitch`): shown at once, back to the saved value on a failure. */
function EnabledSetting({ policy }: { policy: HelperChatPolicy }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useSettingSwitch(
    "helper-chat-policy:enabled",
    policy.enabled,
    async (value) => {
      const next = await updateHelperChatPolicy(browserApi, { enabled: value });
      queryClient.setQueryData(HELPER_CHAT_POLICY_KEY, next);
    },
    // The answer is the whole policy, so there is nothing to read again.
    { queue: HELPER_CHAT_POLICY_QUEUE, onSaved: () => {} }
  );
  return (
    <SettingsGroup id="helper-access" title={t("admin_helper_access_group")}>
      <Switch
        label={t("admin_helper_enabled_label")}
        description={t("admin_helper_enabled_description")}
        value={enabled}
        labelPosition="start"
        labelSpacing="spread"
        width="100%"
        onChange={setEnabled}
      />
    </SettingsGroup>
  );
}

/**
 * The default model of every helper chat, the flow chat's included: the
 * organisation's enabled models that can use tools, or the space's default.
 * Saves on choice; the picker shows the choice while it saves and the saved
 * model again after a refusal, which is shown at the field and announced.
 */
function DefaultModelSetting({ policy }: { policy: HelperChatPolicy }) {
  const t = useTranslations();
  const { tenant, settings } = useAppContext();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const catalog = useQuery(adminModelsQueryOptions(browserApi));
  const [refusal, setRefusal] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (completionModelId: string | null) =>
      updateHelperChatPolicy(browserApi, { completion_model_id: completionModelId }),
    scope: settingSwitchScope(HELPER_CHAT_POLICY_QUEUE),
    onSuccess: (next) => {
      queryClient.setQueryData(HELPER_CHAT_POLICY_KEY, next);
      // The flow chat's settings show the same value.
      void queryClient.invalidateQueries({ queryKey: FLOW_SETTINGS_KEY });
      announce(t("admin_helper_model_saved"));
    },
    onError: (error) => {
      const message = modelRefusalMessage(error, t);
      setRefusal(message);
      announce(message);
    }
  });

  /** The picker shows the choice while it saves and falls back when the promise rejects. */
  function choose(completionModelId: string | null) {
    setRefusal(null);
    return save.mutateAsync(completionModelId);
  }

  const selectedId = policy.completion_model_id ?? null;
  return (
    <SettingsGroup id="helper-model" title={t("admin_helper_model_group")}>
      <div className="max-w-md">
        <ModelSelector
          models={toolCapableCompletionModels(catalog.data)}
          selectedId={selectedId}
          onSelect={choose}
          defaultChoice={{
            label: t("admin_helper_model_space_default"),
            modelId: null,
            isSelected: selectedId === null,
            onSelect: () => choose(null)
          }}
          field={{
            label: t("admin_helper_model_label"),
            description: `${t("admin_helper_model_description")} ${t("admin_helper_model_shared")}`
          }}
          disabled={catalog.isPending}
          showPricing={tenant.show_model_pricing}
          status={refusal ? { type: "error", message: refusal } : undefined}
        />
      </div>
      {settings.flows_enabled === true ? (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          <Link href={FLOW_CHAT_SETTINGS_HREF} hasUnderline className="pointer-coarse:min-h-11">
            {t("admin_helper_model_flow_link")}
          </Link>
        </Text>
      ) : null}
    </SettingsGroup>
  );
}
