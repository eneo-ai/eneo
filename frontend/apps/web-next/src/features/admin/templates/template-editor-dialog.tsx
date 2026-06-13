"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import {
  APP_KEY,
  ASSISTANT_KEY,
  type AppTemplate,
  type AssistantTemplate,
  createAppTemplate,
  createAssistantTemplate,
  updateAppTemplate,
  updateAssistantTemplate
} from "./templates";

type TemplateKind = "assistants" | "apps";
type EditableTemplate = AssistantTemplate | AppTemplate;

const NO_MODEL = "__none__";

export function TemplateEditorDialog({
  kind,
  template,
  open,
  onOpenChange
}: {
  kind: TemplateKind;
  template?: EditableTemplate | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const isApp = kind === "apps";
  const editing = Boolean(template);

  const { data: models } = useQuery({ ...adminModelsQueryOptions(browserApi), enabled: open });

  const [name, setName] = useState(template?.name ?? "");
  const [category, setCategory] = useState(template?.category ?? "");
  const [description, setDescription] = useState(template?.description ?? "");
  const [prompt, setPrompt] = useState(template?.prompt_text ?? "");
  const [modelId, setModelId] = useState(template?.completion_model_id ?? NO_MODEL);
  const [iconName, setIconName] = useState(template?.icon_name ?? "");
  const [inputType, setInputType] = useState(
    template && "input_type" in template ? (template.input_type ?? "text") : "text"
  );
  const [inputDescription, setInputDescription] = useState(
    template && "input_description" in template ? (template.input_description ?? "") : ""
  );

  const save = useMutation({
    mutationFn: () => {
      const completionModelId = modelId === NO_MODEL ? null : modelId;
      const base = {
        name: name.trim(),
        category: category.trim(),
        description: description.trim() || null,
        prompt: prompt.trim() || null,
        completion_model_id: completionModelId,
        icon_name: iconName.trim() || null
      };
      if (isApp) {
        const appBody = {
          ...base,
          input_type: inputType.trim() || "text",
          input_description: inputDescription.trim() || null
        };
        return editing
          ? updateAppTemplate(browserApi, template!.id, appBody)
          : createAppTemplate(browserApi, appBody);
      }
      return editing
        ? updateAssistantTemplate(browserApi, template!.id, base)
        : createAssistantTemplate(browserApi, base);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: isApp ? APP_KEY : ASSISTANT_KEY });
      toast.success(editing ? t("template_updated") : t("template_created"));
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? t("edit_template") : t("new_template")}</DialogTitle>
          <DialogDescription>
            {isApp ? t("create_app_template") : t("create_assistant_template")}
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-name">{t("template_name")}</Label>
            <Input
              id="template-name"
              value={name}
              required
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-category">{t("category")}</Label>
            <Input
              id="template-category"
              value={category}
              required
              onChange={(event) => setCategory(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-description">{t("description")}</Label>
            <Textarea
              id="template-description"
              value={description}
              rows={2}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-prompt">{t("prompt")}</Label>
            <Textarea
              id="template-prompt"
              value={prompt}
              rows={4}
              onChange={(event) => setPrompt(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-model">{t("completion_model")}</Label>
            <Select value={modelId} onValueChange={setModelId}>
              <SelectTrigger id="template-model" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_MODEL}>{t("none")}</SelectItem>
                {(models?.completion_models ?? []).map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    {model.nickname ?? model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {isApp && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="template-input-type">{t("input_type")}</Label>
                <Input
                  id="template-input-type"
                  value={inputType}
                  onChange={(event) => setInputType(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="template-input-description">{t("input_description")}</Label>
                <Textarea
                  id="template-input-description"
                  value={inputDescription}
                  rows={2}
                  onChange={(event) => setInputDescription(event.target.value)}
                />
              </div>
            </>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-icon">
              {t("icon_name")} <span className="text-muted-foreground">({t("optional")})</span>
            </Label>
            <Input
              id="template-icon"
              value={iconName}
              onChange={(event) => setIconName(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!name.trim() || !category.trim() || save.isPending}>
              {save.isPending ? t("saving") : editing ? t("save") : t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
