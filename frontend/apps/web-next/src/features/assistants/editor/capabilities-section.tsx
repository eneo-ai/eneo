"use client";

import { useTranslations } from "next-intl";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  CAPABILITIES,
  capabilityBlockReason,
  readinessKey,
  toggleCapability
} from "@/features/capabilities/capabilities";
import { useSpace } from "@/features/spaces/use-space";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

export function CapabilitiesSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("capabilities");
  const governed = assistant.effective_config?.mcp_enforced === true;
  const selected = governed
    ? (assistant.effective_config?.enabled_capabilities ?? [])
    : (assistant.enabled_capabilities ?? []);
  const editable = assistant.permissions?.includes("edit") ?? false;

  return (
    <SettingsGroup
      title={t("capabilities")}
      description={t(governed ? "functions_policy_description" : "capabilities_row_description")}
    >
      {CAPABILITIES.map((capability) => {
        const enabled = selected.includes(capability.purpose);
        const offered = (space.enabled_capabilities ?? []).includes(capability.purpose);
        const availability = (
          assistant.available_capabilities ?? space.available_capabilities
        )?.find((item) => item.purpose === capability.purpose);
        const blocked = capabilityBlockReason({
          enabled,
          spaceEnabled: offered,
          available: availability?.available === true,
          modelSupportsTools: assistant.completion_model?.supports_tool_calling !== false
        });
        const hint = blocked
          ? t(
              readinessKey(
                blocked === "no_active_provider" ? (availability?.reason ?? blocked) : blocked
              )
            )
          : t(capability.assistantHint);
        return (
          <div key={capability.purpose} className="flex items-center gap-3 rounded-lg border p-4">
            <capability.icon aria-hidden="true" className="text-muted-foreground size-5 shrink-0" />
            <div className="min-w-0 flex-1">
              <Label htmlFor={`assistant-${capability.purpose}`}>{t(capability.purpose)}</Label>
              <p className="text-muted-foreground text-sm">{hint}</p>
            </div>
            <Switch
              id={`assistant-${capability.purpose}`}
              checked={enabled}
              disabled={governed || !editable || update.isPending || blocked !== null}
              onCheckedChange={() =>
                void autosave(() =>
                  update.mutateAsync({
                    enabled_capabilities: toggleCapability(selected, capability.purpose)
                  })
                )
              }
            />
          </div>
        );
      })}
    </SettingsGroup>
  );
}
