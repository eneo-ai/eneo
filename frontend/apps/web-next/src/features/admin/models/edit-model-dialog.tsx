"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { type CompletionModelAdmin, MODELS_KEY, updateCompletionModel } from "./models";

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

/** Full metadata edit for a tenant (custom) completion model. */
export function EditModelDialog({
  model,
  open,
  onOpenChange
}: {
  model: CompletionModelAdmin;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const [displayName, setDisplayName] = useState(model.nickname ?? model.name);
  const [description, setDescription] = useState(model.description ?? "");
  const [maxInput, setMaxInput] = useState(String(model.max_input_tokens ?? ""));
  const [maxOutput, setMaxOutput] = useState(String(model.max_output_tokens ?? ""));
  const [inputCost, setInputCost] = useState(perTokenToPerMillion(model.input_cost_per_token));
  const [outputCost, setOutputCost] = useState(perTokenToPerMillion(model.output_cost_per_token));
  const [vision, setVision] = useState(model.vision ?? false);
  const [reasoning, setReasoning] = useState(model.reasoning ?? false);
  const [tools, setTools] = useState(model.supports_tool_calling ?? false);

  const save = useMutation({
    mutationFn: () =>
      updateCompletionModel(browserApi, model.id, {
        display_name: displayName.trim(),
        description: description.trim() || null,
        max_input_tokens: maxInput ? Number(maxInput) : undefined,
        max_output_tokens: maxOutput ? Number(maxOutput) : undefined,
        input_cost_per_token: perMillionToPerToken(inputCost),
        output_cost_per_token: perMillionToPerToken(outputCost),
        vision,
        reasoning,
        supports_tool_calling: tools
      }),
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
            save.mutate();
          }}
        >
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
          </div>

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

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
