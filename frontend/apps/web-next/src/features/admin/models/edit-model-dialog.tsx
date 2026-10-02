"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { SecurityClassification } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import {
  IMAGE_QUALITIES,
  IMAGE_SIZES,
  type ImageQuality,
  type ImageSize,
  isImageQuality,
  isImageSize,
  useImageOptionLabels
} from "./image-model-options";
import { type AdminModel, MODELS_KEY, type ModelKind, updateTenantModel } from "./models";

/** Stored cost is per-token (tiny); the form edits the friendlier per-1M value. */
function perTokenToPerMillion(value: number | string | null | undefined): string {
  if (value == null) return "";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "";
  return String(Number((n * 1_000_000).toFixed(6)));
}
function perMillionToPerToken(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n / 1_000_000 : null;
}
function numericOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}
function hasTools(model: AdminModel): model is AdminModel & { supports_tool_calling?: boolean } {
  return "supports_tool_calling" in model;
}

/** Token limits and token prices apply to the kinds priced per token. */
const TOKEN_PRICED: ReadonlySet<ModelKind> = new Set(["completion", "embedding"]);

/**
 * Full metadata edit for a tenant (custom) model: the fields of its kind
 * (token limits and prices, per-minute price, or an image model's per-image
 * price and request defaults) plus hosting, stability and classification.
 */
export function EditModelDialog({
  model,
  kind,
  classifications,
  securityEnabled,
  open,
  onOpenChange
}: {
  model: AdminModel;
  kind: ModelKind;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const imageLabels = useImageOptionLabels();

  const [displayName, setDisplayName] = useState(model.nickname ?? model.name);
  const [litellmName, setLitellmName] = useState(model.name);
  const [description, setDescription] = useState(model.description ?? "");
  const [family, setFamily] = useState(model.family ?? "");
  const [hosting, setHosting] = useState(model.hosting ?? "");
  const [stability, setStability] = useState(model.stability ?? "");
  const [openSource, setOpenSource] = useState(model.open_source ?? false);
  const [maxInput, setMaxInput] = useState(
    "max_input_tokens" in model
      ? String(model.max_input_tokens ?? "")
      : "max_input" in model
        ? String(model.max_input ?? "")
        : ""
  );
  const [maxOutput, setMaxOutput] = useState(
    "max_output_tokens" in model ? String(model.max_output_tokens ?? "") : ""
  );
  const [dimensions, setDimensions] = useState(
    "dimensions" in model ? String(model.dimensions ?? "") : ""
  );
  const [inputCost, setInputCost] = useState(
    perTokenToPerMillion("input_cost_per_token" in model ? model.input_cost_per_token : undefined)
  );
  const [outputCost, setOutputCost] = useState(
    perTokenToPerMillion("output_cost_per_token" in model ? model.output_cost_per_token : undefined)
  );
  const [costPerMinute, setCostPerMinute] = useState(
    "cost_per_minute" in model ? String(model.cost_per_minute ?? "") : ""
  );
  const [costPerImage, setCostPerImage] = useState(
    "cost_per_image" in model ? String(model.cost_per_image ?? "") : ""
  );
  const [defaultSize, setDefaultSize] = useState<ImageSize>(
    "default_size" in model && isImageSize(model.default_size) ? model.default_size : "auto"
  );
  const [defaultQuality, setDefaultQuality] = useState<ImageQuality>(
    "default_quality" in model && isImageQuality(model.default_quality)
      ? model.default_quality
      : "auto"
  );
  const [vision, setVision] = useState("vision" in model ? (model.vision ?? false) : false);
  const [reasoning, setReasoning] = useState(
    "reasoning" in model ? (model.reasoning ?? false) : false
  );
  const [tools, setTools] = useState(
    hasTools(model) ? (model.supports_tool_calling ?? false) : false
  );
  const [classificationId, setClassificationId] = useState(
    model.security_classification?.id ?? "__none__"
  );

  const save = useMutation({
    mutationFn: () => {
      const security_classification =
        securityEnabled && classificationId !== "__none__" ? { id: classificationId } : null;
      if (kind === "embedding") {
        return updateTenantModel(browserApi, "embedding", model.id, {
          display_name: displayName.trim(),
          description: description.trim() || null,
          family: family.trim() || null,
          dimensions: numericOrNull(dimensions),
          max_input: numericOrNull(maxInput),
          hosting: hosting.trim() || null,
          open_source: openSource,
          stability: stability.trim() || null,
          input_cost_per_token: perMillionToPerToken(inputCost),
          output_cost_per_token: perMillionToPerToken(outputCost),
          security_classification
        });
      }
      if (kind === "image") {
        return updateTenantModel(browserApi, "image", model.id, {
          display_name: displayName.trim(),
          description: description.trim() || null,
          hosting: hosting.trim() || null,
          open_source: openSource,
          stability: stability.trim() || null,
          cost_per_image: numericOrNull(costPerImage),
          default_size: defaultSize,
          default_quality: defaultQuality,
          security_classification
        });
      }
      if (kind === "transcription") {
        return updateTenantModel(browserApi, "transcription", model.id, {
          display_name: displayName.trim(),
          description: description.trim() || null,
          hosting: hosting.trim() || null,
          open_source: openSource,
          stability: stability.trim() || null,
          cost_per_minute: numericOrNull(costPerMinute),
          security_classification
        });
      }
      return updateTenantModel(browserApi, "completion", model.id, {
        name: litellmName.trim(),
        display_name: displayName.trim(),
        description: description.trim() || null,
        max_input_tokens: maxInput ? Number(maxInput) : undefined,
        max_output_tokens: maxOutput ? Number(maxOutput) : undefined,
        hosting: hosting.trim() || null,
        open_source: openSource,
        stability: stability.trim() || null,
        input_cost_per_token: perMillionToPerToken(inputCost),
        output_cost_per_token: perMillionToPerToken(outputCost),
        vision,
        reasoning,
        supports_tool_calling: tools,
        security_classification
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      toast.success(t("model_updated_success"));
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("edit_model")}</DialogTitle>
          <DialogDescription>{model.name}</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!save.isPending) save.mutate();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="model-litellm-name">{t("model_identifier")}</Label>
            <Input
              id="model-litellm-name"
              value={litellmName}
              onChange={(event) => setLitellmName(event.target.value)}
              readOnly={kind !== "completion"}
              required
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="model-display-name">{t("display_name")}</Label>
            <Input
              id="model-display-name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="model-description">{t("description")}</Label>
            <Textarea
              id="model-description"
              value={description}
              rows={3}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="model-family">{t("model_family")}</Label>
              <Input
                id="model-family"
                value={family}
                onChange={(event) => setFamily(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="model-hosting">{t("hosting_region")}</Label>
              <Input
                id="model-hosting"
                value={hosting}
                onChange={(event) => setHosting(event.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="model-stability">{t("stability")}</Label>
              <Input
                id="model-stability"
                value={stability}
                onChange={(event) => setStability(event.target.value)}
              />
            </div>
            <Label className="flex items-center justify-between gap-2 self-end font-normal">
              {t("open_source")}
              <Switch checked={openSource} onCheckedChange={setOpenSource} />
            </Label>
          </div>

          {TOKEN_PRICED.has(kind) && (
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="model-max-input">{t("max_input_tokens")}</Label>
                <Input
                  id="model-max-input"
                  type="number"
                  min={0}
                  inputMode="numeric"
                  value={maxInput}
                  onChange={(event) => setMaxInput(event.target.value)}
                />
              </div>
              {kind === "completion" ? (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="model-max-output">{t("max_output_tokens")}</Label>
                  <Input
                    id="model-max-output"
                    type="number"
                    min={0}
                    inputMode="numeric"
                    value={maxOutput}
                    onChange={(event) => setMaxOutput(event.target.value)}
                  />
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="model-dimensions">{t("dimensions")}</Label>
                  <Input
                    id="model-dimensions"
                    type="number"
                    min={0}
                    inputMode="numeric"
                    value={dimensions}
                    onChange={(event) => setDimensions(event.target.value)}
                  />
                </div>
              )}
            </div>
          )}

          {kind === "transcription" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="model-cost-minute">{t("cost_per_minute")}</Label>
              <Input
                id="model-cost-minute"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                value={costPerMinute}
                onChange={(event) => setCostPerMinute(event.target.value)}
              />
            </div>
          )}

          {kind === "image" && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="model-cost-image">{t("cost_per_image")}</Label>
                <Input
                  id="model-cost-image"
                  type="number"
                  min={0}
                  step="any"
                  inputMode="decimal"
                  value={costPerImage}
                  aria-describedby="model-cost-image-help"
                  onChange={(event) => setCostPerImage(event.target.value)}
                />
                <p id="model-cost-image-help" className="text-muted-foreground text-xs">
                  {t("cost_per_image_help")}
                </p>
              </div>
              {/* The request defaults the image tool uses when the assistant does not ask. */}
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="model-default-size">{t("image_default_size")}</Label>
                  <Select
                    value={defaultSize}
                    onValueChange={(value) => isImageSize(value) && setDefaultSize(value)}
                  >
                    <SelectTrigger
                      id="model-default-size"
                      className="w-full"
                      aria-describedby="model-default-size-help"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {IMAGE_SIZES.map((size) => (
                        <SelectItem key={size} value={size}>
                          {imageLabels.size(size)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p id="model-default-size-help" className="text-muted-foreground text-xs">
                    {t("image_default_size_help")}
                  </p>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="model-default-quality">{t("image_default_quality")}</Label>
                  <Select
                    value={defaultQuality}
                    onValueChange={(value) => isImageQuality(value) && setDefaultQuality(value)}
                  >
                    <SelectTrigger
                      id="model-default-quality"
                      className="w-full"
                      aria-describedby="model-default-quality-help"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {IMAGE_QUALITIES.map((quality) => (
                        <SelectItem key={quality} value={quality}>
                          {imageLabels.quality(quality)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p id="model-default-quality-help" className="text-muted-foreground text-xs">
                    {t("image_default_quality_help")}
                  </p>
                </div>
              </div>
            </>
          )}

          {TOKEN_PRICED.has(kind) && (
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="model-input-cost">{t("input_cost_per_token")}</Label>
                <Input
                  id="model-input-cost"
                  type="number"
                  min={0}
                  step="any"
                  inputMode="decimal"
                  value={inputCost}
                  aria-describedby="model-input-cost-help"
                  onChange={(event) => setInputCost(event.target.value)}
                />
                <p id="model-input-cost-help" className="text-muted-foreground text-xs">
                  {t("input_cost_per_token_help")}
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="model-output-cost">{t("output_cost_per_token")}</Label>
                <Input
                  id="model-output-cost"
                  type="number"
                  min={0}
                  step="any"
                  inputMode="decimal"
                  value={outputCost}
                  aria-describedby="model-output-cost-help"
                  onChange={(event) => setOutputCost(event.target.value)}
                />
                <p id="model-output-cost-help" className="text-muted-foreground text-xs">
                  {t("output_cost_per_token_help")}
                </p>
              </div>
            </div>
          )}

          {securityEnabled && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="model-security-classification">{t("security_classification")}</Label>
              <Select value={classificationId} onValueChange={setClassificationId}>
                <SelectTrigger id="model-security-classification" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">{t("none")}</SelectItem>
                  {classifications.map((classification) => (
                    <SelectItem key={classification.id} value={classification.id}>
                      {classification.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {kind === "completion" && (
            <fieldset className="flex flex-col gap-3">
              <legend className="text-muted-foreground mb-1 text-xs font-semibold tracking-wider uppercase">
                {t("capabilities")}
              </legend>
              <Label className="flex items-center justify-between gap-2 font-normal">
                {t("capability_vision")}
                <Switch checked={vision} onCheckedChange={setVision} />
              </Label>
              <Label className="flex items-center justify-between gap-2 font-normal">
                {t("reasoning")}
                <Switch checked={reasoning} onCheckedChange={setReasoning} />
              </Label>
              <Label className="flex items-center justify-between gap-2 font-normal">
                {t("model_label_tool_calling")}
                <Switch checked={tools} onCheckedChange={setTools} />
              </Label>
            </fieldset>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            {/* Busy, it stays enabled so it keeps focus; a second submit is ignored. */}
            <Button type="submit" aria-busy={save.isPending || undefined}>
              {save.isPending ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
