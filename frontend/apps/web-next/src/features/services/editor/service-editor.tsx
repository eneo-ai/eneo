"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import {
  useAutosave,
  useAutosaveField,
  useDirtySaveStatus
} from "@/components/composites/use-autosave";
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

export function ServiceEditor({ service }: { service: Service }) {
  const t = useTranslations();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const update = useUpdateService(service.id);
  const autosaveAi = useAutosave("service-ai");
  const autosaveOutput = useAutosave("service-output");

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

  const savedOutputFormat = service.output_format ?? null;
  const savedJsonSchema = useMemo(() => schemaText(service.json_schema), [service.json_schema]);
  const [outputFormat, setOutputFormat] = useState<ServiceOutputFormat | null>(savedOutputFormat);
  const [jsonSchema, setJsonSchema] = useState(savedJsonSchema);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  const savedOutputKey = JSON.stringify([savedOutputFormat, savedJsonSchema]);
  const savedOutputRef = useRef(savedOutputKey);
  useEffect(() => {
    if (savedOutputRef.current === savedOutputKey) return;
    const previous = savedOutputRef.current;
    savedOutputRef.current = savedOutputKey;
    if (JSON.stringify([outputFormat, jsonSchema]) === previous) {
      setOutputFormat(savedOutputFormat);
      setJsonSchema(savedJsonSchema);
      setSchemaError(null);
    }
  }, [savedOutputKey, savedOutputFormat, savedJsonSchema, outputFormat, jsonSchema]);

  const outputDirty =
    outputFormat !== savedOutputFormat ||
    (outputFormat === "json" && jsonSchema !== savedJsonSchema);
  useDirtySaveStatus("service-output", outputDirty);

  const persistOutput = useCallback(
    (nextFormat: ServiceOutputFormat | null = outputFormat, nextJsonSchema = jsonSchema) => {
      let parsedSchema: Record<string, unknown> | null = null;
      if (nextFormat === "json") {
        if (!nextJsonSchema.trim()) {
          setSchemaError(t("required_field"));
          return Promise.resolve(undefined);
        }
        try {
          parsedSchema = parseJsonSchema(nextJsonSchema);
        } catch {
          setSchemaError(t("invalid_format"));
          return Promise.resolve(undefined);
        }
      }
      setSchemaError(null);
      return autosaveOutput(() =>
        update.mutateAsync({
          output_format: nextFormat,
          json_schema: nextFormat === "json" ? parsedSchema : null
        })
      );
    },
    [autosaveOutput, jsonSchema, outputFormat, t, update]
  );

  useEffect(() => {
    if (!outputDirty) return;
    const timer = window.setTimeout(() => void persistOutput(), 750);
    return () => window.clearTimeout(timer);
  }, [outputDirty, persistOutput]);

  useEffect(() => {
    if (!outputDirty) return;
    const handler = () => {
      if (document.visibilityState === "hidden") void persistOutput();
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [outputDirty, persistOutput]);

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
            value={outputFormat ?? NONE}
            onValueChange={(value) => {
              const nextFormat = value === NONE ? null : (value as ServiceOutputFormat);
              setOutputFormat(nextFormat);
              void persistOutput(nextFormat, jsonSchema);
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

        {outputFormat === "json" && (
          <SettingsRow title={t("json_schema")} htmlFor="service-json-schema">
            <Textarea
              id="service-json-schema"
              value={jsonSchema}
              rows={12}
              className="font-mono text-sm"
              aria-invalid={schemaError ? true : undefined}
              onChange={(event) => setJsonSchema(event.target.value)}
              onBlur={() => void persistOutput(outputFormat, jsonSchema)}
            />
            {schemaError && <p className="text-destructive text-sm">{schemaError}</p>}
          </SettingsRow>
        )}
      </SettingsGroup>
    </div>
  );
}
