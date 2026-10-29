"use client";

import { useTranslations } from "use-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave, useAutosaveField } from "@/components/composites/use-autosave";
import { useAppContext } from "@/components/providers/app-context";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  BEHAVIOUR_LIST,
  behaviourFromKwargs,
  filterSupportedKwargs,
  isSelectKwarg,
  kwargCapability,
  kwargsForBehaviour,
  modelKwargLabel,
  modelKwargOptionLabel,
  modelSpecificKwargs,
  supportsBehaviorPresets,
  type ModelBehaviour,
  type ModelKwargName,
  type ModelKwargs
} from "@/features/assistants/editor/model-kwargs";
import { useSpace } from "@/features/spaces/use-space";
import type { Service, ServiceOutputFormat } from "../services";
import { useUpdateService } from "./use-service";

const NONE = "__none";

const NUMERIC_DEFAULT_MAX: Partial<Record<ModelKwargName, number>> = {
  top_p: 1,
  presence_penalty: 2,
  frequency_penalty: 2,
  top_k: 100
};

function schemaText(schema: Service["json_schema"]): string {
  return schema ? JSON.stringify(schema, null, 2) : "";
}

function parseJsonSchema(value: string): Record<string, unknown> {
  const parsed = JSON.parse(value) as unknown;
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON schema must be an object");
  }
  return parsed as Record<string, unknown>;
}

type OutputDraft = { format: ServiceOutputFormat | null; schema: string };

/** JSON with object keys sorted (arrays keep their order): JSONB keeps no key order. */
function sortedKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortedKeys);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, sortedKeys((value as Record<string, unknown>)[key])])
  );
}

/** A schema's content for comparison; text that is no schema yet stays as typed. */
function canonicalSchema(text: string): string {
  try {
    return JSON.stringify(sortedKeys(parseJsonSchema(text)));
  } catch {
    return text;
  }
}

/**
 * The schema only counts while the output format is JSON, and by content: a
 * saved schema renders pretty-printed, so the typed text never matches it.
 */
function outputEquals(a: OutputDraft, b: OutputDraft): boolean {
  return (
    a.format === b.format &&
    (a.format !== "json" || canonicalSchema(a.schema) === canonicalSchema(b.schema))
  );
}

function outputSchemaProblem(output: OutputDraft): "required_field" | "invalid_format" | null {
  if (output.format !== "json") return null;
  if (!output.schema.trim()) return "required_field";
  try {
    parseJsonSchema(output.schema);
    return null;
  } catch {
    return "invalid_format";
  }
}

export function ServiceEditor({ service }: { service: Service }) {
  const t = useTranslations();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const update = useUpdateService(service.id);
  const autosaveAi = useAutosave("service-ai");

  const name = useAutosaveField({
    key: "service-edit-name",
    value: service.name,
    normalize: (value: string) => value.trim(),
    validate: (value) => value.length > 0,
    save: (value) => update.mutateAsync({ name: value })
  });

  const prompt = useAutosaveField({
    key: "service-edit-prompt",
    value: service.prompt,
    validate: (value) => value.trim().length > 0,
    commitDebounceMs: 750,
    commitOnVisibilityChange: true,
    save: (value) => update.mutateAsync({ prompt: value })
  });

  const savedModelId = service.completion_model?.id ?? "";
  const savedKwargs = useMemo<ModelKwargs>(
    () => service.completion_model_kwargs ?? {},
    [service.completion_model_kwargs]
  );
  const [modelId, setModelId] = useState(savedModelId);
  const [kwargs, setKwargs] = useState<ModelKwargs>(savedKwargs);

  const savedAiKey = JSON.stringify([savedModelId, savedKwargs]);
  const savedAiRef = useRef(savedAiKey);
  useEffect(() => {
    if (savedAiRef.current === savedAiKey) return;
    const previous = savedAiRef.current;
    savedAiRef.current = savedAiKey;
    if (JSON.stringify([modelId, kwargs]) === previous) {
      setModelId(savedModelId);
      setKwargs(savedKwargs);
    }
  }, [savedAiKey, savedModelId, savedKwargs, modelId, kwargs]);

  const model = space.completion_models.find((candidate) => candidate.id === modelId) ?? null;
  const behaviour = behaviourFromKwargs(kwargs);
  const presetsSupported = model === null || supportsBehaviorPresets(model);
  const specificKwargs = modelSpecificKwargs(model);
  const temperatureCap = kwargCapability(model, "temperature");

  const persistAi = useCallback(
    (nextModelId: string, nextKwargs: ModelKwargs) => {
      const targetModel =
        space.completion_models.find((candidate) => candidate.id === nextModelId) ?? null;
      return autosaveAi(() =>
        update.mutateAsync({
          completion_model: nextModelId ? { id: nextModelId } : null,
          completion_model_kwargs: filterSupportedKwargs(nextKwargs, targetModel)
        })
      );
    },
    [autosaveAi, space.completion_models, update]
  );

  function changeModel(nextModelId: string) {
    setModelId(nextModelId);
    void persistAi(nextModelId, kwargs);
  }

  function changeKwargs(next: ModelKwargs, save = true) {
    setKwargs(next);
    if (save) void persistAi(modelId, next);
  }

  function selectBehaviour(next: ModelBehaviour) {
    const preset = kwargsForBehaviour(next);
    if (preset) {
      changeKwargs({ ...kwargs, temperature: preset.temperature });
    } else if (behaviourFromKwargs(kwargs) !== "custom") {
      changeKwargs({ ...kwargs, temperature: 1 });
    }
  }

  const savedOutput = useMemo<OutputDraft>(
    () => ({ format: service.output_format ?? null, schema: schemaText(service.json_schema) }),
    [service.output_format, service.json_schema]
  );
  const output = useAutosaveField({
    key: "service-output",
    value: savedOutput,
    equals: outputEquals,
    validate: (draft) => outputSchemaProblem(draft) === null,
    save: (draft) =>
      update.mutateAsync({
        output_format: draft.format,
        json_schema: draft.format === "json" ? parseJsonSchema(draft.schema) : null
      }),
    commitDebounceMs: 750,
    commitOnVisibilityChange: true
  });
  const schemaProblem = outputSchemaProblem(output.value);

  return (
    <div className="flex flex-col gap-6 py-4">
      <SettingsGroup title={t("general")}>
        <SettingsRow title={t("name")} htmlFor="service-edit-name">
          <Input
            id="service-edit-name"
            value={name.value}
            aria-invalid={!name.value.trim() || undefined}
            onChange={(event) => name.setValue(event.target.value)}
            onBlur={() => void name.commit()}
          />
          {!name.value.trim() && <p className="text-destructive text-sm">{t("required_field")}</p>}
        </SettingsRow>

        <SettingsRow title={t("prompt")} htmlFor="service-edit-prompt">
          <Textarea
            id="service-edit-prompt"
            value={prompt.value}
            rows={6}
            aria-invalid={!prompt.value.trim() || undefined}
            onChange={(event) => prompt.setValue(event.target.value)}
            onBlur={() => void prompt.commit()}
          />
          {!prompt.value.trim() && (
            <p className="text-destructive text-sm">{t("required_field")}</p>
          )}
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title={t("ai_settings")}>
        <SettingsRow
          title={t("completion_model")}
          description={t("this_model_will_be_used")}
          htmlFor="service-completion-model"
        >
          <ModelSelector
            id="service-completion-model"
            models={space.completion_models}
            selectedId={modelId}
            onSelect={changeModel}
            className="w-full justify-between"
            showPricing={tenant.show_model_pricing}
          />
        </SettingsRow>

        {presetsSupported && (
          <SettingsRow
            title={t("model_behaviour")}
            description={t("select_preset_behavior")}
            htmlFor="service-model-behaviour"
          >
            <div className="flex flex-col gap-3">
              <Select
                value={behaviour}
                disabled={!model}
                onValueChange={(value) => selectBehaviour(value as ModelBehaviour)}
              >
                <SelectTrigger id="service-model-behaviour" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BEHAVIOUR_LIST.map((candidate) => (
                    <SelectItem key={candidate} value={candidate}>
                      {candidate === "creative"
                        ? t("creative")
                        : candidate === "default"
                          ? t("default_behavior")
                          : candidate === "deterministic"
                            ? t("deterministic")
                            : t("custom")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {behaviour === "custom" && (
                <div className="flex items-center gap-2">
                  <Label htmlFor="service-temperature" className="text-muted-foreground">
                    {t("temperature")}
                  </Label>
                  <Input
                    id="service-temperature"
                    type="number"
                    className="w-28"
                    min={temperatureCap?.minimum ?? 0}
                    max={temperatureCap?.maximum ?? 2}
                    step={temperatureCap?.step ?? 0.05}
                    value={kwargs.temperature ?? 1}
                    onChange={(event) =>
                      changeKwargs({ ...kwargs, temperature: Number(event.target.value) }, false)
                    }
                    onBlur={() => void persistAi(modelId, kwargs)}
                  />
                </div>
              )}
            </div>
          </SettingsRow>
        )}

        {specificKwargs.length > 0 && (
          <SettingsRow title={t("model_settings")} description={t("model_settings_description")}>
            <div className="flex flex-col gap-3">
              {specificKwargs.map((name) => {
                const capability = kwargCapability(model, name);
                return (
                  <div key={name} className="flex items-center justify-between gap-4">
                    <Label
                      htmlFor={`service-kwarg-${name}`}
                      className="text-muted-foreground font-normal"
                    >
                      {modelKwargLabel(name, t)}
                    </Label>
                    {isSelectKwarg(name) ? (
                      <Select
                        value={(kwargs[name] as string | null | undefined) ?? NONE}
                        onValueChange={(value) =>
                          changeKwargs({ ...kwargs, [name]: value === NONE ? null : value })
                        }
                      >
                        <SelectTrigger id={`service-kwarg-${name}`} className="w-44">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NONE}>{t("default_behavior")}</SelectItem>
                          {(capability?.options ?? []).map((option) => (
                            <SelectItem key={option} value={option}>
                              {modelKwargOptionLabel(option, t)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        id={`service-kwarg-${name}`}
                        type="number"
                        className="w-28"
                        min={capability?.minimum ?? 0}
                        max={capability?.maximum ?? NUMERIC_DEFAULT_MAX[name] ?? 1}
                        step={capability?.step ?? 0.05}
                        value={(kwargs[name] as number | null | undefined) ?? ""}
                        placeholder="—"
                        onChange={(event) =>
                          changeKwargs(
                            {
                              ...kwargs,
                              [name]: event.target.value === "" ? null : Number(event.target.value)
                            },
                            false
                          )
                        }
                        onBlur={() => void persistAi(modelId, kwargs)}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </SettingsRow>
        )}
      </SettingsGroup>

      <SettingsGroup title={t("output_format")}>
        <SettingsRow title={t("output_format")} htmlFor="service-output-format">
          <Select
            value={output.value.format ?? NONE}
            onValueChange={(value) => {
              const next = {
                ...output.value,
                format: value === NONE ? null : (value as ServiceOutputFormat)
              };
              output.setValue(next);
              void output.commit(next);
            }}
          >
            <SelectTrigger id="service-output-format" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="json">JSON</SelectItem>
              <SelectItem value="list">{t("list")}</SelectItem>
              <SelectItem value="boolean">{t("boolean")}</SelectItem>
              <SelectItem value={NONE}>{t("none")}</SelectItem>
            </SelectContent>
          </Select>
        </SettingsRow>

        {output.value.format === "json" && (
          <SettingsRow title={t("json_schema")} htmlFor="service-json-schema">
            <Textarea
              id="service-json-schema"
              value={output.value.schema}
              rows={12}
              className="font-mono text-sm"
              aria-invalid={schemaProblem ? true : undefined}
              onChange={(event) => {
                const schema = event.target.value;
                output.setValue((current) => ({ ...current, schema }));
              }}
              onBlur={() => void output.commit()}
            />
            {schemaProblem && <p className="text-destructive text-sm">{t(schemaProblem)}</p>}
          </SettingsRow>
        )}
      </SettingsGroup>
    </div>
  );
}
