"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { IconField } from "@/components/composites/icon-field";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave, useAutosaveField } from "@/components/composites/use-autosave";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
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
import { ResourceApiKeysSection } from "@/features/api-keys/resource-api-keys-section";
import { mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import { useSpace } from "@/features/spaces/use-space";
import {
  pruneUnknownMcpServerIds,
  selectedVisibleMcpServerCount,
  visibleSpaceMcpServers
} from "./space-mcp-selection";
import {
  type SpaceSecurityImpact,
  type SpaceSecurityImpactKey,
  securityImpactRows,
  securityImpactTotal
} from "./security-impact";
import { SpaceModelSelect } from "./space-model-select";

type SpaceUpdate = Schema<"PartialUpdateSpaceRequest">;
const SECURITY_IMPACT_LABEL_KEYS: Record<SpaceSecurityImpactKey, string> = {
  assistants: "assistants",
  group_chats: "group_chats",
  apps: "apps",
  services: "services",
  completion_models: "completion_models",
  embedding_models: "embedding_models",
  transcription_models: "transcription_models",
  mcp_servers: "mcp_servers"
};

const sortedKey = (ids: Iterable<string>) => JSON.stringify([...ids].sort());

function useUpdateSpace() {
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();

  // Feedback is owned by the caller's autosave wrapper (useAutosave); this
  // mutation only refreshes the cache.
  return useMutation({
    scope: { id: `space:${space.id}` },
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
    key: "space-name",
    value: space.name,
    save: (value) => update.mutateAsync({ name: value }),
    normalize: (value) => value.trim(),
    validate: (value) => value.length > 0
  });
  const description = useAutosaveField({
    key: "space-description",
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
      <SettingsRow title={t("avatar")} description={t("avatar_description")}>
        <IconField
          iconId={space.icon_id}
          onSave={(iconId) => update.mutateAsync({ icon_id: iconId })}
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
  const [loadingImpact, setLoadingImpact] = useState(false);
  const [pendingImpact, setPendingImpact] = useState<{
    classificationId: string;
    impact: SpaceSecurityImpact;
  } | null>(null);

  const { data: security } = useQuery({
    queryKey: ["security-classifications"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/security-classifications/"))
  });

  const NONE = "__none__";
  const currentClassificationId = space.security_classification?.id ?? NONE;

  async function saveSecurityClassification(value: string) {
    return autosave(() =>
      update.mutateAsync({
        security_classification: value === NONE ? null : { id: value }
      })
    );
  }

  async function requestSecurityClassificationChange(value: string) {
    if (value === currentClassificationId) return;
    if (value === NONE) {
      await saveSecurityClassification(value);
      return;
    }

    setLoadingImpact(true);
    try {
      const impact = await unwrap(
        browserApi.GET(
          "/api/v1/spaces/{id}/security_classification/{security_classification_id}/impact-analysis/",
          {
            params: {
              path: { id: space.id, security_classification_id: value }
            }
          }
        )
      );
      if (securityImpactTotal(impact) === 0) {
        await saveSecurityClassification(value);
        return;
      }
      setPendingImpact({ classificationId: value, impact });
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setLoadingImpact(false);
    }
  }

  async function confirmSecurityClassificationChange() {
    if (!pendingImpact) return;
    const result = await saveSecurityClassification(pendingImpact.classificationId);
    if (result !== undefined) setPendingImpact(null);
  }

  const pendingImpactRows = pendingImpact ? securityImpactRows(pendingImpact.impact) : [];
  const pendingImpactTotal = pendingImpact ? securityImpactTotal(pendingImpact.impact) : 0;

  return (
    <SettingsGroup id="security" title={t("security_and_privacy")}>
      {security?.security_enabled && (
        <SettingsRow
          title={t("security_classification")}
          description={t("security_classification_description")}
        >
          <Select
            value={currentClassificationId}
            disabled={update.isPending || loadingImpact}
            onValueChange={(value) => void requestSecurityClassificationChange(value)}
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
          <AlertDialog
            open={pendingImpact !== null}
            onOpenChange={(open) => !open && setPendingImpact(null)}
          >
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t("migration_impact")}</AlertDialogTitle>
                <AlertDialogDescription>
                  {t("migration_impact_title", { count: pendingImpactTotal })}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium">{t("affected_resources")}</p>
                <ul className="text-muted-foreground grid gap-1 text-sm">
                  {pendingImpactRows.map((row) => (
                    <li key={row.key} className="flex justify-between gap-4">
                      <span>{t(SECURITY_IMPACT_LABEL_KEYS[row.key])}</span>
                      <span className="tabular-nums">{row.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={update.isPending}>{t("cancel")}</AlertDialogCancel>
                <Button
                  disabled={update.isPending}
                  onClick={() => void confirmSecurityClassificationChange()}
                >
                  {update.isPending ? t("saving") : t("confirm")}
                </Button>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
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
    key: "retention-days",
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
      <McpServersSection />
    </SettingsGroup>
  );
}

function McpServersSection() {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateSpace();
  const autosave = useAutosave("models");

  const { data: mcpServers, isPending } = useQuery(mcpServersQueryOptions(browserApi));
  const savedIds = (space.mcp_servers ?? []).map((server) => server.id);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(savedIds));

  const savedKey = sortedKey(savedIds);
  const savedRef = useRef(savedKey);
  useEffect(() => {
    if (savedRef.current === savedKey) return;
    const previous = savedRef.current;
    savedRef.current = savedKey;
    setSelected((current) => (sortedKey(current) === previous ? new Set(savedIds) : current));
  }, [savedKey, savedIds]);

  const candidates = visibleSpaceMcpServers(mcpServers ?? [], savedIds);
  const knownIds = new Set(candidates.map((server) => server.id));
  const activeCount = selectedVisibleMcpServerCount(candidates, selected);

  function toggle(id: string, on: boolean) {
    const previous = selected;
    const next = new Set(pruneUnknownMcpServerIds(selected, knownIds));
    if (on) next.add(id);
    else next.delete(id);
    const attemptedKey = sortedKey(next);
    setSelected(next);
    void autosave(() =>
      update.mutateAsync({ mcp_servers: [...next].map((serverId) => ({ id: serverId })) })
    ).then((result) => {
      if (result !== undefined) return;
      setSelected((current) => (sortedKey(current) === attemptedKey ? previous : current));
    });
  }

  return (
    <SettingsRow title={t("mcp_servers")} description={t("select_mcp_servers_description")}>
      {isPending ? (
        <p className="text-muted-foreground text-sm">{t("loading")}</p>
      ) : candidates.length === 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-muted-foreground text-sm">{t("enable_mcp_servers_in_admin")}</p>
          <Button asChild variant="outline" size="sm">
            <Link href="/admin/mcp-servers">{t("mcp_servers")}</Link>
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <p
            className="text-muted-foreground text-sm"
            aria-label={t("mcp_servers_status_aria", {
              active: activeCount,
              total: candidates.length
            })}
          >
            {t("mcp_servers_active_count", { active: activeCount, total: candidates.length })}
          </p>
          <fieldset className="flex flex-col gap-2" aria-label={t("mcp_servers")}>
            {candidates.map((server) => (
              <Label
                key={server.id}
                className="border-border flex items-center justify-between gap-3 rounded-lg border p-3 font-normal"
              >
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="font-medium">{server.name}</span>
                  {server.description && (
                    <span className="text-muted-foreground line-clamp-1 text-xs">
                      {server.description}
                    </span>
                  )}
                </span>
                <Switch
                  checked={selected.has(server.id)}
                  disabled={update.isPending || (!server.is_available && !selected.has(server.id))}
                  aria-label={server.name}
                  onCheckedChange={(on) => toggle(server.id, on)}
                />
              </Label>
            ))}
          </fieldset>
        </div>
      )}
    </SettingsRow>
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

function SpaceApiKeysSection() {
  const { space } = useSpace();
  return <ResourceApiKeysSection scopeType="space" scopeId={space.id} resourceName={space.name} />;
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
        <SpaceApiKeysSection />
        {!isOrgSpace && can("delete", "space") && <DangerSection />}
      </div>
    </SaveStatusProvider>
  );
}
