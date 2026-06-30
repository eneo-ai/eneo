"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave, useAutosaveField } from "@/components/composites/use-autosave";
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
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";
import { SpaceModelSelect } from "./space-model-select";

type SpaceUpdate = Schema<"PartialUpdateSpaceRequest">;

function useUpdateSpace() {
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();

  // Feedback is owned by the caller's autosave wrapper (useAutosave); this
  // mutation only refreshes the cache.
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
    }
  });
}

function GeneralSection() {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateSpace();

  const name = useAutosaveField({
    key: "general",
    value: space.name,
    save: (value) => update.mutateAsync({ name: value }),
    normalize: (value) => value.trim()
  });
  const description = useAutosaveField({
    key: "general",
    value: space.description ?? "",
    save: (value) => update.mutateAsync({ description: value })
  });

  return (
    <SettingsGroup id="general" title={t("general")}>
      <SettingsRow title={t("name")} description={t("space_name_description")} htmlFor="space-name">
        <Input
          id="space-name"
          value={name.value}
          onChange={(event) => name.setValue(event.target.value)}
          // A space must keep a name — revert an emptied field on blur.
          onBlur={() => (name.value.trim() ? name.commit() : name.reset())}
        />
      </SettingsRow>
      <SettingsRow
        title={t("description")}
        description={t("space_description_description")}
        htmlFor="space-description"
      >
        <Textarea
          id="space-description"
          value={description.value}
          rows={4}
          onChange={(event) => description.setValue(event.target.value)}
          onBlur={() => description.commit()}
        />
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
  const autosave = useAutosave("security");

  const { data: security } = useQuery({
    queryKey: ["security-classifications"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/security-classifications/"))
  });

  const NONE = "__none__";

  return (
    <SettingsGroup id="security" title={t("security_and_privacy")}>
      {security?.security_enabled && (
        <SettingsRow
          title={t("security_classification")}
          description={t("security_classification_description")}
        >
          <Select
            value={space.security_classification?.id ?? NONE}
            disabled={update.isPending}
            onValueChange={(value) =>
              autosave(() =>
                update.mutateAsync({
                  security_classification: value === NONE ? null : { id: value }
                })
              )
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

  const days = useAutosaveField({
    key: "security",
    value: space.data_retention_days?.toString() ?? "",
    save: (value) =>
      update.mutateAsync({ data_retention_days: value === "" ? null : Number(value) }),
    // Empty means "keep forever"; otherwise require a positive whole number.
    validate: (value) => value === "" || (Number.isInteger(Number(value)) && Number(value) >= 1)
  });

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
          value={days.value}
          placeholder="∞"
          onChange={(event) => days.setValue(event.target.value)}
          onBlur={() => days.commit()}
        />
        <span className="text-muted-foreground text-sm">{t("days")}</span>
      </div>
    </SettingsRow>
  );
}

function ModelsSection() {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateSpace();
  const autosave = useAutosave("models");

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
    <SettingsGroup id="models" title={t("advanced_settings")}>
      <SpaceModelSelect
        kind="completion"
        title={t("completion_models")}
        description={t("completion_models_description")}
        models={completionModels}
        selectedIds={space.completion_models.map((model) => model.id)}
        pending={update.isPending}
        onChange={(ids) => autosave(() => update.mutateAsync({ completion_models: toIds(ids) }))}
      />
      <SpaceModelSelect
        kind="embedding"
        title={t("embedding_models")}
        description={t("embedding_models_description")}
        models={embeddingModels}
        selectedIds={space.embedding_models.map((model) => model.id)}
        pending={update.isPending}
        onChange={(ids) => autosave(() => update.mutateAsync({ embedding_models: toIds(ids) }))}
      />
      <SpaceModelSelect
        kind="transcription"
        title={t("transcription_models")}
        description={t("transcription_models_description")}
        models={transcriptionModels}
        selectedIds={space.transcription_models.map((model) => model.id)}
        pending={update.isPending}
        onChange={(ids) => autosave(() => update.mutateAsync({ transcription_models: toIds(ids) }))}
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
    <SaveStatusProvider>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-10">
        <PageHeader title={t("settings")}>
          <SaveStatusIndicator />
        </PageHeader>
        {!isOrgSpace && <GeneralSection />}
        {!isOrgSpace && <SecuritySection />}
        <ModelsSection />
        {!isOrgSpace && can("delete", "space") && <DangerSection />}
      </div>
    </SaveStatusProvider>
  );
}
