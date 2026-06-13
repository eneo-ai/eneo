"use client";

import { AlertCircle, Cpu } from "lucide-react";
import { useTranslations } from "next-intl";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { PolicySection } from "./policy-section";
import type { PolicyDraft } from "./use-policy-draft";

export function ModelRestrictionSection({ draft }: { draft: PolicyDraft }) {
  const t = useTranslations();
  const {
    modelsEnabled,
    setModelsEnabled,
    modelsByProvider,
    modelSelections,
    providerSelections,
    effectiveModelIds,
    defaultModelId,
    modelsSummary,
    defaultValid,
    badgeVariant,
    providerName,
    setSingleDefault,
    toggleModelSelected,
    toggleProvider
  } = draft;

  return (
    <PolicySection
      id="models"
      title={t("governance_models_heading")}
      description={t("governance_models_section_desc")}
      summary={modelsSummary}
      summaryVariant={badgeVariant(modelsEnabled, effectiveModelIds.size > 0 && defaultValid)}
      icon={<Cpu className="size-5" />}
    >
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor="models-enabled" className="text-sm font-medium">
          {t("governance_models_toggle_label")}
        </Label>
        <Switch
          id="models-enabled"
          checked={modelsEnabled}
          onCheckedChange={setModelsEnabled}
          aria-describedby="models-help"
        />
      </div>

      {modelsEnabled ? (
        <>
          <p id="models-help" className="text-muted-foreground text-sm">
            {t("governance_models_help_enabled")}
          </p>
          {/* One default model across all providers, so a single radio group wraps every table. */}
          <RadioGroup
            value={defaultModelId ?? ""}
            onValueChange={(value) => value && setSingleDefault(value)}
            className="gap-3"
          >
            {[...modelsByProvider.entries()].map(([pid, providerModels]) => {
              const isProviderSelected = pid !== null && providerSelections.has(pid);
              return (
                <fieldset key={pid ?? "_unprovided"} className="overflow-hidden rounded-lg border">
                  <legend className="sr-only">{providerName(pid)}</legend>
                  <div className="bg-muted flex items-center justify-between gap-3 border-b px-4 py-3">
                    <div className="flex items-center gap-3">
                      {pid !== null ? (
                        <Switch
                          checked={isProviderSelected}
                          onCheckedChange={(value) => toggleProvider(pid, value)}
                          aria-label={t("governance_provider_allow_all_aria", {
                            provider: providerName(pid)
                          })}
                        />
                      ) : (
                        <div className="w-8" aria-hidden="true" />
                      )}
                      <div>
                        <div className="text-foreground text-sm font-semibold">
                          {providerName(pid)}
                        </div>
                        <div className="text-muted-foreground text-xs">
                          {isProviderSelected
                            ? t("governance_provider_all_allowed")
                            : pid === null
                              ? t("governance_provider_no_provider_desc")
                              : providerModels.length === 1
                                ? t("governance_provider_model_count_one", {
                                    count: providerModels.length
                                  })
                                : t("governance_provider_model_count_other", {
                                    count: providerModels.length
                                  })}
                        </div>
                      </div>
                    </div>
                  </div>
                  <table
                    className="w-full text-sm"
                    aria-label={t("governance_models_table_aria", { provider: providerName(pid) })}
                  >
                    <thead className="sr-only">
                      <tr>
                        <th scope="col">{t("governance_col_allow")}</th>
                        <th scope="col">{t("governance_col_model")}</th>
                        <th scope="col">{t("governance_col_default")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {providerModels.map((model) => {
                        const includedViaProvider = isProviderSelected;
                        const effectivelySelected =
                          includedViaProvider || (modelSelections[model.id]?.selected ?? false);
                        const modelName = model.nickname ?? model.name;
                        return (
                          <tr
                            key={model.id}
                            className={`border-t ${includedViaProvider ? "bg-muted/40" : ""}`}
                          >
                            <td className="w-14 px-4 py-2.5">
                              <Switch
                                checked={effectivelySelected}
                                disabled={includedViaProvider}
                                onCheckedChange={(value) => toggleModelSelected(model.id, value)}
                                aria-label={t("governance_model_allow_aria", { name: modelName })}
                              />
                            </td>
                            <td className="px-4 py-2.5">
                              <span className={includedViaProvider ? "text-muted-foreground" : ""}>
                                {modelName}
                              </span>
                              {includedViaProvider && (
                                <span className="text-muted-foreground ml-1.5 text-xs">
                                  {t("governance_via_provider")}
                                </span>
                              )}
                            </td>
                            <td className="w-20 px-4 py-2.5">
                              <div className="flex items-center gap-2">
                                <RadioGroupItem
                                  value={model.id}
                                  id={`default-${model.id}`}
                                  disabled={!effectivelySelected}
                                  aria-label={t("governance_model_set_default_aria", {
                                    name: modelName
                                  })}
                                />
                                <Label
                                  htmlFor={`default-${model.id}`}
                                  className="text-muted-foreground text-xs"
                                >
                                  {t("governance_default_label")}
                                </Label>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </fieldset>
              );
            })}
          </RadioGroup>
          {effectiveModelIds.size === 0 ? (
            <p className="text-destructive flex items-center gap-2 text-sm" role="alert">
              <AlertCircle className="size-4 shrink-0" aria-hidden="true" />
              {t("governance_models_error_none")}
            </p>
          ) : !defaultValid ? (
            <p className="text-destructive flex items-center gap-2 text-sm" role="alert">
              <AlertCircle className="size-4 shrink-0" aria-hidden="true" />
              {t("governance_models_error_default_invalid")}
            </p>
          ) : null}
        </>
      ) : (
        <p id="models-help" className="text-muted-foreground text-sm">
          {t("governance_models_help_disabled")}
        </p>
      )}
    </PolicySection>
  );
}
