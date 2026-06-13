"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
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
import { useSpace } from "@/features/spaces/use-space";
import {
  BEHAVIOUR_LIST,
  behaviourFromKwargs,
  filterSupportedKwargs,
  isSelectKwarg,
  kwargCapability,
  kwargsForBehaviour,
  modelSpecificKwargs,
  supportsBehaviorPresets,
  type ModelBehaviour,
  type ModelKwargName,
  type ModelKwargs
} from "@/features/assistants/editor/model-kwargs";
import type { Service, ServiceOutputFormat } from "../services";
import { useUpdateService } from "./use-service";

const NONE = "__none";

function kwargLabel(name: ModelKwargName, t: (key: string) => string): string {
  switch (name) {
    case "reasoning_effort":
      return t("reasoning_effort");
    case "verbosity":
      return t("verbosity");
    case "top_p":
      return t("top_p");
    case "presence_penalty":
      return t("presence_penalty");
    case "frequency_penalty":
      return t("frequency_penalty");
    case "top_k":
      return t("top_k");
    default:
      return name;
  }
}

export function ServiceEditor({ service }: { service: Service }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateService(service.id);

  const [name, setName] = useState(service.name);
  const [prompt, setPrompt] = useState(service.prompt);
  const [modelId, setModelId] = useState(service.completion_model?.id ?? "");
  const [kwargs, setKwargs] = useState<ModelKwargs>(service.completion_model_kwargs ?? {});
  const [outputFormat, setOutputFormat] = useState<ServiceOutputFormat | null>(
    service.output_format ?? null
  );
  const [jsonSchema, setJsonSchema] = useState(
    service.json_schema ? JSON.stringify(service.json_schema, null, 2) : ""
  );

  const model = space.completion_models.find((candidate) => candidate.id === modelId) ?? null;
  const behaviour = behaviourFromKwargs(kwargs);
  const presetsSupported = model === null || supportsBehaviorPresets(model);
  const specificKwargs = modelSpecificKwargs(model);
  const temperatureCap = kwargCapability(model, "temperature");

  function selectBehaviour(next: ModelBehaviour) {
    const preset = kwargsForBehaviour(next);
    if (preset) {
      setKwargs((current) => ({ ...current, temperature: preset.temperature }));
    } else if (behaviourFromKwargs(kwargs) !== "custom") {
      setKwargs((current) => ({ ...current, temperature: 1 }));
    }
  }

  function save() {
    if (!name.trim() || !prompt.trim()) {
      toast.warning(t("required_field"));
      return;
    }
    let parsedSchema: Record<string, unknown> | null = null;
    if (outputFormat === "json") {
      if (!jsonSchema.trim()) {
        toast.warning(t("required_field"));
        return;
      }
      try {
        parsedSchema = JSON.parse(jsonSchema) as Record<string, unknown>;
      } catch {
        toast.error(t("invalid_format"));
        return;
      }
    }

    update.mutate({
      name: name.trim(),
      prompt,
      completion_model: modelId ? { id: modelId } : null,
      completion_model_kwargs: filterSupportedKwargs(kwargs, model),
      output_format: outputFormat,
      json_schema: outputFormat === "json" ? parsedSchema : null
    });
  }

  return (
    <div className="flex flex-col gap-6 py-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="service-edit-name">{t("name")}</Label>
        <Input
          id="service-edit-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="service-edit-prompt">{t("prompt")}</Label>
        <Textarea
          id="service-edit-prompt"
          value={prompt}
          rows={6}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label>{t("completion_model")}</Label>
        <Select value={modelId} onValueChange={setModelId}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder={t("choose_a_completion_model")} />
          </SelectTrigger>
          <SelectContent>
            {space.completion_models.map((candidate) => (
              <SelectItem key={candidate.id} value={candidate.id}>
                {candidate.nickname ?? candidate.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {presetsSupported && (
        <div className="flex flex-col gap-2">
          <Label>{t("model_behaviour")}</Label>
          <Select
            value={behaviour}
            disabled={!model}
            onValueChange={(value) => selectBehaviour(value as ModelBehaviour)}
          >
            <SelectTrigger className="w-full" aria-label={t("select_model_behaviour")}>
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
                  setKwargs((current) => ({ ...current, temperature: Number(event.target.value) }))
                }
              />
            </div>
          )}
        </div>
      )}

      {specificKwargs.length > 0 && (
        <div className="flex flex-col gap-2">
          <Label>{t("model_settings")}</Label>
          {specificKwargs.map((kwargName) => {
            const capability = kwargCapability(model, kwargName);
            return (
              <div key={kwargName} className="flex items-center justify-between gap-4">
                <Label className="text-muted-foreground font-normal">
                  {kwargLabel(kwargName, t)}
                </Label>
                {isSelectKwarg(kwargName) ? (
                  <Select
                    value={(kwargs[kwargName] as string | null | undefined) ?? NONE}
                    onValueChange={(value) =>
                      setKwargs((current) => ({
                        ...current,
                        [kwargName]: value === NONE ? null : value
                      }))
                    }
                  >
                    <SelectTrigger className="w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>{t("default_behavior")}</SelectItem>
                      {(capability?.options ?? []).map((option) => (
                        <SelectItem key={option} value={option}>
                          {option}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    type="number"
                    className="w-28"
                    min={capability?.minimum ?? 0}
                    max={capability?.maximum ?? 1}
                    step={capability?.step ?? 0.05}
                    value={(kwargs[kwargName] as number | null | undefined) ?? ""}
                    placeholder="—"
                    onChange={(event) =>
                      setKwargs((current) => ({
                        ...current,
                        [kwargName]: event.target.value === "" ? null : Number(event.target.value)
                      }))
                    }
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="flex flex-col gap-2">
        <Label>{t("output_format")}</Label>
        <Select
          value={outputFormat ?? NONE}
          onValueChange={(value) =>
            setOutputFormat(value === NONE ? null : (value as ServiceOutputFormat))
          }
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="json">JSON</SelectItem>
            <SelectItem value="list">{t("list")}</SelectItem>
            <SelectItem value="boolean">{t("boolean")}</SelectItem>
            <SelectItem value={NONE}>{t("none")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {outputFormat === "json" && (
        <div className="flex flex-col gap-2">
          <Label htmlFor="service-json-schema">{t("json_schema")}</Label>
          <Textarea
            id="service-json-schema"
            value={jsonSchema}
            rows={12}
            className="font-mono text-sm"
            onChange={(event) => setJsonSchema(event.target.value)}
          />
        </div>
      )}

      <div className="sticky bottom-0 flex justify-end py-2">
        <Button className="w-36" disabled={update.isPending} onClick={save}>
          {update.isPending ? t("saving") : t("save")}
        </Button>
      </div>
    </div>
  );
}
