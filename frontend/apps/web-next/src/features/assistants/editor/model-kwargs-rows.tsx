"use client";

import { useTranslations } from "next-intl";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
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
  isValidNumericKwarg,
  kwargCapability,
  kwargsForBehaviour,
  modelKwargLabel,
  modelKwargOptionLabel,
  modelSpecificKwargs,
  numericKwargRange,
  supportsBehaviorPresets,
  type ModelBehaviour,
  type ModelKwargs,
  type ModelWithKwargs,
  type NumericSettingName
} from "./model-kwargs";

const BEHAVIOUR_LABEL_KEYS: Record<ModelBehaviour, string> = {
  creative: "creative",
  default: "default_behavior",
  deterministic: "deterministic",
  custom: "custom"
};

/** The id of a number setting's field, for focusing the first one that cannot be saved. */
export function modelKwargFieldId(idPrefix: string, name: NumericSettingName): string {
  return name === "temperature" ? `${idPrefix}-custom-temperature` : `${idPrefix}-kwarg-${name}`;
}

/**
 * The model behaviour preset (with a custom temperature) and the settings the
 * chosen model supports, as two settings rows: the Svelte SelectBehaviourV2
 * and SelectModelSpecificSettings. Presets set the temperature, so they are
 * disabled (and read "Standard") for a model without temperature support,
 * with a note saying why. `onChange` reports each edit; `commit` is false
 * while a number is being typed, and `onCommit` runs when that field is left.
 * With `showProblems`, a typed number outside its range (or a fraction where a
 * whole number is needed) says so at its field (`firstInvalidNumericKwarg`
 * finds the first). The caller strips what the model does not support when it
 * saves (`filterSupportedKwargs`).
 */
export function ModelKwargsRows({
  idPrefix,
  model,
  kwargs,
  behaviourDescription,
  showProblems = false,
  onChange,
  onCommit
}: {
  idPrefix: string;
  model: ModelWithKwargs | null;
  kwargs: ModelKwargs;
  behaviourDescription: string;
  showProblems?: boolean;
  onChange: (next: ModelKwargs, commit: boolean) => void;
  onCommit?: () => void;
}) {
  const t = useTranslations();
  const presetsSupported = supportsBehaviorPresets(model);
  const behaviour = presetsSupported ? behaviourFromKwargs(kwargs) : "default";
  const specificKwargs = modelSpecificKwargs(model);
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

  function numberField(name: NumericSettingName, value: number | null | undefined) {
    const id = modelKwargFieldId(idPrefix, name);
    const range = numericKwargRange(model, name);
    const problem =
      showProblems && !isValidNumericKwarg(model, name, value)
        ? t(
            range.wholeNumber ? "form_problem_whole_number_between" : "form_problem_number_between",
            {
              min: range.min,
              max: range.max
            }
          )
        : null;
    return (
      <div key={name} className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-4">
          <Label htmlFor={id} className="text-muted-foreground font-normal">
            {modelKwargLabel(name, t)}
          </Label>
          <Input
            id={id}
            type="number"
            className="w-28"
            min={range.min}
            max={range.max}
            step={range.step}
            value={value ?? ""}
            placeholder={t("default_behavior")}
            onChange={(event) => {
              const typed = event.target.value;
              // Emptied, a setting goes back to the model's default; the custom
              // temperature stays custom (0), as it did before it moved here.
              const next = typed === "" && name !== "temperature" ? null : Number(typed);
              onChange({ ...kwargs, [name]: next }, false);
            }}
            onBlur={onCommit}
            {...fieldProblemProps(id, problem)}
          />
        </div>
        <FieldProblem id={id} problem={problem} />
      </div>
    );
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
            <div className="sm:max-w-80">{numberField("temperature", kwargs.temperature ?? 1)}</div>
          )}
        </div>
      </SettingsRow>

      {specificKwargs.length > 0 && (
        <SettingsRow title={t("model_settings")} description={t("model_settings_description")}>
          <div className="flex flex-col gap-3">
            {specificKwargs.map((name) => {
              if (!isSelectKwarg(name)) {
                return numberField(name, kwargs[name] as number | null | undefined);
              }
              const id = `${idPrefix}-kwarg-${name}`;
              return (
                <div key={name} className="flex items-center justify-between gap-4">
                  <Label htmlFor={id} className="text-muted-foreground font-normal">
                    {modelKwargLabel(name, t)}
                  </Label>
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
                      {(kwargCapability(model, name)?.options ?? []).map((option) => (
                        <SelectItem key={option} value={option}>
                          {modelKwargOptionLabel(option, t)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              );
            })}
          </div>
        </SettingsRow>
      )}
    </>
  );
}
