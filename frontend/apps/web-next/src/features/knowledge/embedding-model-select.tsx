"use client";

import { useTranslations } from "next-intl";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import type { EmbeddingModel } from "./knowledge";

function displayName(model: EmbeddingModel): string {
  return model.open_source ? `${model.name} (Open Source)` : model.name;
}

/**
 * Embedding model picker for knowledge creation, grouped by stability like
 * the Svelte SelectEmbeddingModel. Hidden when there is at most one option
 * (the caller defaults to the first model).
 */
export function EmbeddingModelSelect({
  models,
  value,
  onChange
}: {
  models: EmbeddingModel[];
  value: string | undefined;
  onChange: (id: string) => void;
}) {
  const t = useTranslations();
  if (models.length < 2) return null;

  const stable = models.filter((model) => model.stability === "stable");
  const experimental = models.filter((model) => model.stability === "experimental");

  return (
    <div className="flex flex-col gap-2">
      <Label>{t("embedding_model")}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="w-full">
          <SelectValue placeholder={t("select_ellipsis")} />
        </SelectTrigger>
        <SelectContent>
          {stable.length > 0 && (
            <SelectGroup>
              <SelectLabel>{t("stable_embedding_models")}</SelectLabel>
              {stable.map((model) => (
                <SelectItem key={model.id} value={model.id}>
                  {displayName(model)}
                </SelectItem>
              ))}
            </SelectGroup>
          )}
          {experimental.length > 0 && (
            <SelectGroup>
              <SelectLabel>{t("experimental_embedding_models")}</SelectLabel>
              {experimental.map((model) => (
                <SelectItem key={model.id} value={model.id}>
                  {displayName(model)}
                </SelectItem>
              ))}
            </SelectGroup>
          )}
        </SelectContent>
      </Select>
    </div>
  );
}
