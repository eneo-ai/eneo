import { useTranslations } from "use-intl";
import {
  SettingsGroup,
  SettingsMarkLabel,
  useSettingsMarks
} from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  CAPABILITIES,
  capabilityBlockReason,
  readinessKey,
  toggleCapability,
  type CapabilityDescriptor
} from "@/features/capabilities/capabilities";
import type { Space } from "@/features/spaces/space";
import { useSpace } from "@/features/spaces/use-space";
import { cn } from "@/lib/utils";
import {
  capabilityAvailability,
  capabilityBlockMessageKey,
  capabilityControlId,
  capabilityRowId,
  modelBlocksTools as blocksTools
} from "./assistant-editor-rules";
import { AssistantDocumentTemplateChoice } from "./document-template-choice";
import { assistantToolModel } from "./effective-config";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

/** The capabilities the assistant has: the policy's where a policy governs them. */
export function selectedCapabilities(assistant: Assistant) {
  return assistant.effective_config?.mcp_enforced === true
    ? (assistant.effective_config?.enabled_capabilities ?? [])
    : (assistant.enabled_capabilities ?? []);
}

/** What the section reads of the space: the functions it offers, their readiness and its models. */
export type CapabilitySpace = Pick<
  Space,
  "enabled_capabilities" | "available_capabilities" | "completion_models"
>;

/** A function as the section lists it: on or off, and why its switch cannot be switched on. */
export type CapabilityRow = {
  capability: CapabilityDescriptor;
  enabled: boolean;
  blocked: ReturnType<typeof capabilityBlockReason>;
};

/**
 * The functions the section lists, in its order: under a policy that governs
 * them only the policy's, each with whether it is on and why it cannot be
 * switched on (`capabilityBlockReason`). The helper chat's references to the
 * functions read the same.
 */
export function capabilityRows(assistant: Assistant, space: CapabilitySpace): CapabilityRow[] {
  const governed = assistant.effective_config?.mcp_enforced === true;
  const selected = selectedCapabilities(assistant);
  // A picked model without tool calling never receives a capability: it reads
  // as unavailable, and only an already-enabled one can be switched off. No
  // model picked is a separate state and does not block.
  const modelBlocksTools = blocksTools(
    assistantToolModel(space.completion_models ?? [], assistant)
  );
  return CAPABILITIES.filter(
    (capability) => !governed || selected.includes(capability.purpose)
  ).map((capability) => {
    const enabled = selected.includes(capability.purpose);
    return {
      capability,
      enabled,
      blocked: capabilityBlockReason({
        enabled,
        spaceEnabled: (space.enabled_capabilities ?? []).includes(capability.purpose),
        available: capabilityAvailability(assistant, space, capability.purpose)?.available === true,
        modelSupportsTools: !modelBlocksTools
      })
    };
  });
}

export function CapabilitiesSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("capabilities");
  const governed = assistant.effective_config?.mcp_enforced === true;
  const selected = selectedCapabilities(assistant);
  const editable = assistant.permissions?.includes("edit") ?? false;
  // Under a policy, a hint says first that the chat model cannot use tools.
  const modelBlocksTools = blocksTools(
    assistantToolModel(space.completion_models ?? [], assistant)
  );
  // A function a change from the helper chat switched is marked for a while.
  const marks = useSettingsMarks();

  return (
    <SettingsGroup
      title={t("capabilities")}
      description={t(governed ? "functions_policy_description" : "capabilities_row_description")}
    >
      {governed && selected.length === 0 && (
        <p className="text-muted-foreground text-sm">{t("functions_policy_none")}</p>
      )}
      {capabilityRows(assistant, space).map(({ capability, enabled, blocked }) => {
        const availability = capabilityAvailability(assistant, space, capability.purpose);
        const hint = governed
          ? modelBlocksTools
            ? t("tools_readiness_model_no_tool_calling")
            : availability?.available !== true
              ? t(readinessKey(availability?.reason ?? "no_active_provider"))
              : t(capability.assistantHint)
          : blocked
            ? t(capabilityBlockMessageKey(blocked, availability))
            : t(capability.assistantHint);
        const controlId = capabilityControlId(capability.purpose);
        const mark = marks?.rows.has(controlId) ? marks.label : null;
        const label = <Label htmlFor={controlId}>{t(capability.purpose)}</Label>;
        return (
          <div
            key={capability.purpose}
            className={cn("rounded-lg border p-4", mark && "bg-ax-selected")}
          >
            {/* Where a reference to the function lands: its switch, the line's control. */}
            <div id={capabilityRowId(capability.purpose)} className="flex items-center gap-3">
              <capability.icon
                aria-hidden="true"
                className="text-muted-foreground size-5 shrink-0"
              />
              <div className="min-w-0 flex-1">
                {mark ? (
                  // Beside the name, outside it: the switch's name stays the function's.
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    {label}
                    <SettingsMarkLabel label={mark} />
                  </span>
                ) : (
                  label
                )}
                {governed && (
                  <p className="text-muted-foreground text-sm">
                    {t(
                      assistant.effective_config?.default_disabled_capabilities?.includes(
                        capability.purpose
                      )
                        ? "functions_default_off"
                        : "functions_default_on"
                    )}
                  </p>
                )}
                <p className="text-muted-foreground text-sm">{hint}</p>
              </div>
              {/* Saving, it stays enabled so it keeps focus. A toggle meanwhile is
                ignored: each save sends the whole selection. */}
              <Switch
                id={controlId}
                checked={
                  governed
                    ? !assistant.effective_config?.default_disabled_capabilities?.includes(
                        capability.purpose
                      )
                    : enabled
                }
                disabled={governed || !editable || blocked !== null}
                aria-busy={
                  (update.isPending &&
                    update.variables?.enabled_capabilities?.includes(capability.purpose) !==
                      enabled) ||
                  undefined
                }
                onCheckedChange={() => {
                  if (update.isPending) return;
                  void autosave(() =>
                    update.mutateAsync({
                      enabled_capabilities: toggleCapability(selected, capability.purpose)
                    })
                  );
                }}
              />
            </div>
            {capability.purpose === "file_creation" && enabled && (
              <AssistantDocumentTemplateChoice
                assistant={assistant}
                isDisabled={update.isPending}
              />
            )}
          </div>
        );
      })}
    </SettingsGroup>
  );
}
