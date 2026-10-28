"use client";

import { useTranslations } from "next-intl";
import { SettingsRow } from "@/components/composites/settings-rows";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  BEHAVIOUR_LIST,
  behaviourFromKwargs,
  isSelectKwarg,
  kwargCapability,
  kwargsForBehaviour,
  modelKwargLabel,
  modelKwargOptionLabel,
  modelSpecificKwargs,
  supportsBehaviorPresets,
  type ModelBehaviour,
  type ModelKwargName,
  type ModelKwargs,
  type ModelWithKwargs
} from "./model-kwargs";

const NUMERIC_DEFAULT_MAX: Partial<Record<ModelKwargName, number>> = {
  top_p: 1,
  presence_penalty: 2,
  frequency_penalty: 2,
  top_k: 100
};

const BEHAVIOUR_LABEL_KEYS: Record<ModelBehaviour, string> = {
  creative: "creative",
  default: "default_behavior",
  deterministic: "deterministic",
  custom: "custom"
};

/**
 * The model behaviour preset (with a custom temperature) and the settings the
 * chosen model supports, as two settings rows: the Svelte SelectBehaviourV2
 * and SelectModelSpecificSettings. Presets set the temperature, so they are
 * disabled (and read "Standard") for a model without temperature support,
 * with a note saying why. `onChange` reports each edit; `commit` is false
 * while a number is being typed, and `onCommit` runs when that field is left.
 * The caller strips what the model does not support when it saves
 * (`filterSupportedKwargs`).
 */
export function ModelKwargsRows({
  idPrefix,
  model,
  kwargs,
  behaviourDescription,
  onChange,
  onCommit
}: {
  idPrefix: string;
  model: ModelWithKwargs | null;
  kwargs: ModelKwargs;
  behaviourDescription: string;
  onChange: (next: ModelKwargs, commit: boolean) => void;
  onCommit?: () => void;
}) {
  const t = useTranslations();
  const presetsSupported = supportsBehaviorPresets(model);
  const behaviour = presetsSupported ? behaviourFromKwargs(kwargs) : "default";
  const specificKwargs = modelSpecificKwargs(model);
  const temperatureCap = kwargCapability(model, "temperature");
  const behaviourId = `${idPrefix}-model-behaviour`;
  const noteId = `${behaviourId}-note`;
  const note =
    model && !presetsSupported
      ? specificKwargs.length > 0
        ? t("model_uses_specific_parameters_info")
        : t("temperature_not_available")
      : null;

  function selectBehaviour(next: ModelBehaviour) {
    const preset = kwargsForBehaviour(next);
    if (preset) {
      onChange({ ...kwargs, temperature: preset.temperature }, true);
    } else if (behaviourFromKwargs(kwargs) !== "custom") {
      onChange({ ...kwargs, temperature: 1 }, true);
    }
  }

  return (
    <>
      <SettingsRow
        title={t("model_behaviour")}
        description={behaviourDescription}
        htmlFor={behaviourId}
      >
        <div className="flex flex-col gap-3">
          <Select
            value={behaviour}
            disabled={!presetsSupported}
            onValueChange={(value) => selectBehaviour(value as ModelBehaviour)}
          >
            <SelectTrigger
              id={behaviourId}
              className="w-full"
              aria-describedby={note ? noteId : undefined}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BEHAVIOUR_LIST.map((candidate) => (
                <SelectItem key={candidate} value={candidate}>
                  {t(BEHAVIOUR_LABEL_KEYS[candidate])}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {note && (
            <p id={noteId} className="text-muted-foreground text-sm">
              {note}
            </p>
          )}
          {behaviour === "custom" && (
            <div className="flex items-center gap-2">
              <Label htmlFor={`${idPrefix}-custom-temperature`} className="text-muted-foreground">
                {t("temperature")}
              </Label>
              <Input
                id={`${idPrefix}-custom-temperature`}
                type="number"
                className="w-28"
                min={temperatureCap?.minimum ?? 0}
                max={temperatureCap?.maximum ?? 2}
                step={temperatureCap?.step ?? 0.05}
                value={kwargs.temperature ?? 1}
                onChange={(event) =>
                  onChange({ ...kwargs, temperature: Number(event.target.value) }, false)
                }
                onBlur={onCommit}
              />
            </div>
          )}
        </div>
      </SettingsRow>

      {specificKwargs.length > 0 && (
        <SettingsRow title={t("model_settings")} description={t("model_settings_description")}>
          <div className="flex flex-col gap-3">
            {specificKwargs.map((name) => {
              const capability = kwargCapability(model, name);
              const id = `${idPrefix}-kwarg-${name}`;
              return (
                <div key={name} className="flex items-center justify-between gap-4">
                  <Label htmlFor={id} className="text-muted-foreground font-normal">
                    {modelKwargLabel(name, t)}
                  </Label>
                  {isSelectKwarg(name) ? (
                    <Select
                      value={(kwargs[name] as string | null | undefined) ?? "__default"}
                      onValueChange={(value) =>
                        onChange({ ...kwargs, [name]: value === "__default" ? null : value }, true)
                      }
                    >
                      <SelectTrigger id={id} className="w-44">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__default">{t("default_behavior")}</SelectItem>
                        {(capability?.options ?? []).map((option) => (
                          <SelectItem key={option} value={option}>
                            {modelKwargOptionLabel(option, t)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      id={id}
                      type="number"
                      className="w-28"
                      min={capability?.minimum ?? 0}
                      max={capability?.maximum ?? NUMERIC_DEFAULT_MAX[name] ?? 1}
                      step={capability?.step ?? 0.05}
                      value={(kwargs[name] as number | null | undefined) ?? ""}
                      placeholder={t("default_behavior")}
                      onChange={(event) =>
                        onChange(
                          {
                            ...kwargs,
                            [name]: event.target.value === "" ? null : Number(event.target.value)
                          },
                          false
                        )
                      }
                      onBlur={onCommit}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </SettingsRow>
      )}
    </>
  );
}
