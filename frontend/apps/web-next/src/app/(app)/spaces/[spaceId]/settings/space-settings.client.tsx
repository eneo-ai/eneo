"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";

type SpaceUpdate = Schema<"PartialUpdateSpaceRequest">;

function useUpdateSpace() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: SpaceUpdate) =>
      unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/", {
          params: { path: { id: space.id } },
          body
        })
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      queryClient.invalidateQueries({ queryKey: ["spaces"], exact: true });
    },
    onError: (error) => toastApiError(error, t)
  });
}

function GeneralSection() {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateSpace();
  const [name, setName] = useState(space.name);
  const [description, setDescription] = useState(space.description ?? "");

  const dirty = name !== space.name || description !== (space.description ?? "");

  return (
    <SettingsGroup title={t("general")}>
      <SettingsRow title={t("name")} description={t("space_name_description")}>
        <Input value={name} onChange={(event) => setName(event.target.value)} />
      </SettingsRow>
      <SettingsRow title={t("description")} description={t("space_description_description")}>
        <Textarea
          value={description}
          rows={4}
          onChange={(event) => setDescription(event.target.value)}
        />
        <div className="flex justify-end gap-2">
          {dirty && (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setName(space.name);
                  setDescription(space.description ?? "");
                }}
              >
                {t("cancel")}
              </Button>
              <Button
                disabled={update.isPending || !name.trim()}
                onClick={() => update.mutate({ name: name.trim(), description })}
              >
                {update.isPending ? t("loading") : t("save_changes")}
              </Button>
            </>
          )}
        </div>
      </SettingsRow>
      <StorageSection />
    </SettingsGroup>
  );
}

function StorageSection() {
  const t = useTranslations();
  const { space } = useSpace();

  const categories = [
    { label: t("collections"), items: space.knowledge.groups.items },
    { label: t("websites"), items: space.knowledge.websites.items },
    { label: t("integrations"), items: space.knowledge.integration_knowledge_list.items }
  ].map((category) => ({
    label: category.label,
    size: category.items.reduce((sum, item) => sum + (item.metadata?.size ?? 0), 0)
  }));
  const total = categories.reduce((sum, category) => sum + category.size, 0);

  function formatBytes(bytes: number): string {
    if (bytes === 0) return "0 B";
    const units = ["B", "kB", "MB", "GB", "TB"];
    const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1000)), units.length - 1);
    return `${(bytes / 1000 ** exponent).toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
  }

  return (
    <SettingsRow title={t("storage")} description={t("storage_description")}>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>
          <span className="font-medium">{t("total")}</span>: {formatBytes(total)}
        </span>
        {categories.map((category) => (
          <span key={category.label}>
            <span className="font-medium">{category.label}</span>: {formatBytes(category.size)}
          </span>
        ))}
      </div>
    </SettingsRow>
  );
}

function SecuritySection() {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateSpace();

  const { data: security } = useQuery({
    queryKey: ["security-classifications"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/security-classifications/"))
  });

  const NONE = "__none__";

  return (
    <SettingsGroup title={t("security_and_privacy")}>
      {security?.security_enabled && (
        <SettingsRow
          title={t("security_classification")}
          description={t("security_classification_description")}
        >
          <Select
            value={space.security_classification?.id ?? NONE}
            disabled={update.isPending}
            onValueChange={(value) =>
              update.mutate({ security_classification: value === NONE ? null : { id: value } })
            }
          >
            <SelectTrigger className="w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>—</SelectItem>
              {security.security_classifications.map((classification) => (
                <SelectItem key={classification.id} value={classification.id}>
                  {classification.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </SettingsRow>
      )}
      <RetentionSection />
    </SettingsGroup>
  );
}

function RetentionSection() {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateSpace();
  const [days, setDays] = useState<string>(space.data_retention_days?.toString() ?? "");

  const current = space.data_retention_days?.toString() ?? "";
  const dirty = days !== current;

  return (
    <SettingsRow
      title={t("conversation_retention_title")}
      description={t("conversation_retention_space_description")}
    >
      <div className="flex items-center gap-2">
        <Label htmlFor="retention-days" className="sr-only">
          {t("conversation_retention_title")}
        </Label>
        <Input
          id="retention-days"
          type="number"
          min={1}
          className="w-32"
          value={days}
          placeholder="∞"
          onChange={(event) => setDays(event.target.value)}
        />
        <span className="text-muted-foreground text-sm">{t("days")}</span>
        {dirty && (
          <Button
            size="sm"
            disabled={update.isPending}
            onClick={() =>
              update.mutate({ data_retention_days: days === "" ? null : Number(days) })
            }
          >
            {update.isPending ? t("loading") : t("save_changes")}
          </Button>
        )}
      </div>
    </SettingsRow>
  );
}

type ToggleableModel = {
  id: string;
  name: string;
  nickname?: string | null;
  is_org_enabled?: boolean;
  is_deprecated?: boolean;
  meets_security_classification?: boolean | null;
};

function ModelToggleRow({
  models,
  selectedIds,
  title,
  description,
  onChange,
  pending
}: {
  models: ToggleableModel[];
  selectedIds: string[];
  title: string;
  description: string;
  onChange: (ids: string[]) => void;
  pending: boolean;
}) {
  const t = useTranslations();

  function toggle(modelId: string) {
    const next = selectedIds.includes(modelId)
      ? selectedIds.filter((id) => id !== modelId)
      : [...selectedIds, modelId];
    onChange(next);
  }

  return (
    <SettingsRow title={title} description={description}>
      <div className="flex flex-col">
        {models.map((model) => {
          const meetsClassification = model.meets_security_classification ?? true;
          return (
            <div
              key={model.id}
              className={`border-border flex items-center justify-between gap-4 border-b py-3 ${
                meetsClassification ? "" : "opacity-60"
              }`}
              title={
                meetsClassification ? undefined : t("model_does_not_meet_security_classification")
              }
            >
              <span className="text-sm font-medium">{model.nickname ?? model.name}</span>
              <Switch
                checked={selectedIds.includes(model.id)}
                disabled={pending || !meetsClassification}
                onCheckedChange={() => toggle(model.id)}
                aria-label={model.nickname ?? model.name}
              />
            </div>
          );
        })}
      </div>
    </SettingsRow>
  );
}

function ModelsSection() {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateSpace();

  const { data: models } = useQuery({
    queryKey: ["ai-models", space.id],
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/ai-models/", { params: { query: { space_id: space.id } } }))
  });

  const completionModels = (models?.completion_models ?? []).filter(
    (model) => model.is_org_enabled && !model.is_deprecated && !model.migrated_to_model_id
  );
  const embeddingModels = (models?.embedding_models ?? []).filter(
    (model) => model.is_org_enabled && !model.is_deprecated
  );
  const transcriptionModels = (models?.transcription_models ?? []).filter(
    (model) => model.is_org_enabled && !model.is_deprecated && !model.migrated_to_model_id
  );

  const toIds = (modelIds: string[]) => modelIds.map((id) => ({ id }));

  return (
    <SettingsGroup title={t("advanced_settings")}>
      <ModelToggleRow
        title={t("completion_models")}
        description={t("completion_models_description")}
        models={completionModels}
        selectedIds={space.completion_models.map((model) => model.id)}
        pending={update.isPending}
        onChange={(ids) => update.mutate({ completion_models: toIds(ids) })}
      />
      <ModelToggleRow
        title={t("embedding_models")}
        description={t("embedding_models_description")}
        models={embeddingModels}
        selectedIds={space.embedding_models.map((model) => model.id)}
        pending={update.isPending}
        onChange={(ids) => update.mutate({ embedding_models: toIds(ids) })}
      />
      <ModelToggleRow
        title={t("transcription_models")}
        description={t("transcription_models_description")}
        models={transcriptionModels}
        selectedIds={space.transcription_models.map((model) => model.id)}
        pending={update.isPending}
        onChange={(ids) => update.mutate({ transcription_models: toIds(ids) })}
      />
      {/* MCP server selection is stubbed until Phase 6 owns the MCP UI. */}
    </SettingsGroup>
  );
}

function DangerSection() {
  const t = useTranslations();
  const { space } = useSpace();
  const router = useRouter();
  const queryClient = useQueryClient();

  const deleteSpace = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/spaces/{id}/", { params: { path: { id: space.id } } })),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["spaces"] });
      router.push("/spaces/list");
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <SettingsGroup title={t("danger_zone")}>
      <SettingsRow title={t("delete_space")} description={t("delete_space_description")}>
        <div>
          <ConfirmDialog
            trigger={<Button variant="destructive">{t("delete_this_space")}</Button>}
            title={t("delete_space")}
            description={t("confirm_delete_space_message", { space: space.name })}
            confirmLabel={deleteSpace.isPending ? t("deleting") : t("confirm_deletion")}
            confirmValue={space.name}
            confirmValueLabel={t("enter_space_name_to_confirm")}
            pending={deleteSpace.isPending}
            onConfirm={() => deleteSpace.mutateAsync().then(() => undefined)}
          />
        </div>
      </SettingsRow>
    </SettingsGroup>
  );
}

export function SpaceSettings() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const isOrgSpace = space.organization;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-10">
      <PageHeader title={t("settings")} />
      {!isOrgSpace && <GeneralSection />}
      {!isOrgSpace && <SecuritySection />}
      <ModelsSection />
      {!isOrgSpace && can("delete", "space") && <DangerSection />}
    </div>
  );
}
