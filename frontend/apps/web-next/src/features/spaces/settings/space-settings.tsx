"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button as AxButton } from "@astryxdesign/core/Button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import {
  Bot,
  KeyRound,
  Plug,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TriangleAlert
} from "lucide-react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { IconField } from "@/components/composites/icon-field";
import { LoadingState } from "@/components/composites/loading-state";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import {
  SectionedSettings,
  type SettingsSection
} from "@/components/composites/sectioned-settings";
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
import { formatBytes } from "@/lib/format";
import { ResourceApiKeysSection } from "@/features/api-keys/resource-api-keys-section";
import {
  CAPABILITIES,
  capabilityBlockReason,
  readinessKey,
  toggleCapability
} from "@/features/capabilities/capabilities";
import { mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import type { Space } from "@/features/spaces/space";
import { useSpace } from "@/features/spaces/use-space";
import { PageHeader } from "@/components/composites/page-header";
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
import { SpaceModelSelect, type ModelKind, type ModelSelectionChange } from "./space-model-select";

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
const modelKinds: ModelKind[] = ["completion", "embedding", "transcription"];

function modelIds(space: Space, kind: ModelKind): string[] {
  switch (kind) {
    case "completion":
      return space.completion_models.map((model) => model.id);
    case "embedding":
      return space.embedding_models.map((model) => model.id);
    case "transcription":
      return space.transcription_models.map((model) => model.id);
  }
}

function modelUpdate(kind: ModelKind, ids: string[]): SpaceUpdate {
  const refs = ids.map((id) => ({ id }));
  switch (kind) {
    case "completion":
      return { completion_models: refs };
    case "embedding":
      return { embedding_models: refs };
    case "transcription":
      return { transcription_models: refs };
  }
}

function SettingsLoadFailure({
  title,
  retrying,
  onRetry
}: {
  title: string;
  retrying: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations();
  return (
    <Banner
      status="error"
      title={title}
      endContent={
        <AxButton
          label={t("try_again")}
          aria-label={t("space_settings_retry_named", { section: title })}
          variant="secondary"
          isLoading={retrying}
          isInterruptible
          onClick={() => {
            if (!retrying) onRetry();
          }}
        />
      }
    />
  );
}

function useUpdateSpace() {
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();

  // Feedback is owned by the caller's autosave wrapper (useAutosave); this
  // mutation writes the server's full response to the detail cache.
  return useMutation({
    scope: { id: `space:${space.id}` },
    mutationFn: (body: SpaceUpdate) =>
      unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/", {
          params: { path: { id: space.id } },
          body
        })
      ),
    onSuccess: async (saved) => {
      // PATCH returns the authoritative full space. An older GET must not
      // replace it while the detail query is being refreshed.
      await queryClient.cancelQueries({ queryKey: ["spaces", routeId], exact: true });
      queryClient.setQueryData(["spaces", routeId], saved);
      void queryClient.invalidateQueries({ queryKey: ["spaces"], exact: true });
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
  const [nameVisited, setNameVisited] = useState(false);
  const nameProblem =
    nameVisited && !name.value.trim() ? t("shell_create_space_name_required") : null;

  return (
    <SettingsGroup title={t("general")}>
      <SettingsRow title={t("name")} description={t("space_name_description")} htmlFor="space-name">
        <Input
          id="space-name"
          value={name.value}
          onChange={(event) => name.setValue(event.target.value)}
          onBlur={() => {
            setNameVisited(true);
            void name.commit();
          }}
          {...fieldProblemProps("space-name", nameProblem)}
        />
        <FieldProblem id="space-name" problem={nameProblem} />
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
  const locale = useLocale();
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

  return (
    <SettingsRow title={t("storage")} description={t("storage_description")}>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>
          <span className="font-medium">{t("total")}</span>: {formatBytes(total, locale)}
        </span>
        {categories.map((category) => (
          <span key={category.label}>
            <span className="font-medium">{category.label}</span>:{" "}
            {formatBytes(category.size, locale)}
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

  const {
    data: security,
    isPending: securityPending,
    isError: securityError,
    isFetching: securityFetching,
    refetch: refetchSecurity
  } = useQuery({
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
    <SettingsGroup title={t("security_and_privacy")}>
      {securityPending ? <LoadingState rows={1} /> : null}
      {securityError ? (
        <SettingsLoadFailure
          title={t("space_security_load_failed")}
          retrying={securityFetching}
          onRetry={() => void refetchSecurity()}
        />
      ) : null}
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
                {/* Busy, it stays enabled so it keeps focus; a second press is ignored. */}
                <Button
                  aria-busy={update.isPending || undefined}
                  onClick={() => {
                    if (!update.isPending) void confirmSecurityClassificationChange();
                  }}
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

/**
 * The space's retention policy. Only those who may edit the space change it
 * (the backend refuses everyone else); the rest read the value.
 */
function RetentionSection() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const update = useUpdateSpace();
  const readOnlyHintId = useId();
  const canEditRetention = can("edit", "space");
  const [daysVisited, setDaysVisited] = useState(false);

  const validDays = (value: string) =>
    value === "" ||
    (/^[0-9]+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) >= 1);

  const days = useAutosaveField({
    key: "retention-days",
    value: space.data_retention_days?.toString() ?? "",
    save: (value) =>
      update.mutateAsync({ data_retention_days: value === "" ? null : Number(value) }),
    // Empty means "keep forever"; otherwise require a positive whole number.
    validate: validDays
  });
  const daysProblem = daysVisited && !validDays(days.value) ? t("space_retention_invalid") : null;

  return (
    <SettingsRow
      title={t("conversation_retention_title")}
      description={t("conversation_retention_space_description")}
      htmlFor="retention-days"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id="retention-days"
          type="text"
          inputMode="numeric"
          className="w-32"
          value={days.value}
          placeholder={t("space_retention_no_limit_placeholder")}
          onChange={(event) => days.setValue(event.target.value)}
          onBlur={() => {
            setDaysVisited(true);
            void days.commit();
          }}
          disabled={!canEditRetention}
          {...fieldProblemProps(
            "retention-days",
            daysProblem,
            canEditRetention ? undefined : readOnlyHintId
          )}
        />
        <span className="text-muted-foreground text-sm">{t("days")}</span>
      </div>
      <FieldProblem id="retention-days" problem={daysProblem} />
      {!canEditRetention && (
        <p id={readOnlyHintId} className="text-muted-foreground text-sm">
          {t("conversation_retention_space_admin_only")}
        </p>
      )}
    </SettingsRow>
  );
}

function ModelsSection() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const update = useUpdateSpace();
  const autosave = useAutosave("models");
  type ModelOverride = { ids: string[]; pending: boolean };
  type ModelOverrides = Partial<Record<ModelKind, ModelOverride>>;
  const [overrides, setOverrides] = useState<ModelOverrides>({});
  const overridesRef = useRef<ModelOverrides>({});
  const queueRef = useRef<ModelKind[]>([]);
  const drainingRef = useRef(false);
  const [failedKind, setFailedKind] = useState<ModelKind | null>(null);

  function setOverride(kind: ModelKind, value: ModelOverride) {
    const next = { ...overridesRef.current, [kind]: value };
    overridesRef.current = next;
    setOverrides(next);
  }

  // The PATCH scope serializes writes to this space. This queue also coalesces
  // rapid model clicks, so every new intent is visible and the latest one wins.
  async function drainModelChanges() {
    let failedRequest: ModelKind | null = null;
    const saved = await autosave(async () => {
      while (queueRef.current.length > 0) {
        const kind = queueRef.current.shift();
        if (!kind) continue;
        const entry = overridesRef.current[kind];
        if (!entry?.pending) continue;

        const requested = entry.ids;
        const response = await update.mutateAsync(modelUpdate(kind, requested)).catch((error) => {
          failedRequest = kind;
          throw error;
        });
        const accepted = modelIds(response, kind);
        const latest = overridesRef.current[kind];
        if (
          latest &&
          (sortedKey(latest.ids) === sortedKey(requested) ||
            sortedKey(latest.ids) === sortedKey(accepted))
        ) {
          queueRef.current = queueRef.current.filter((queued) => queued !== kind);
          // Keep the accepted value visible until useSpace receives the cache update.
          setOverride(kind, { ids: accepted, pending: false });
        } else if (latest && !queueRef.current.includes(kind)) {
          queueRef.current.push(kind);
        }
      }
      return true;
    });

    if (!saved) {
      queueRef.current = [];
      overridesRef.current = {};
      setOverrides({});
      setFailedKind(failedRequest);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId], exact: true });
    }
    drainingRef.current = false;
    // A click can arrive while useAutosave is finishing, after the loop empties.
    if (queueRef.current.length > 0) {
      drainingRef.current = true;
      void drainModelChanges();
    }
  }

  function changeModels(kind: ModelKind, change: ModelSelectionChange) {
    const current = overridesRef.current[kind]?.ids ?? modelIds(space, kind);
    const next = change(current);
    if (sortedKey(next) === sortedKey(current)) return;
    setFailedKind(null);
    setOverride(kind, { ids: next, pending: true });
    if (!queueRef.current.includes(kind)) queueRef.current.push(kind);
    if (!drainingRef.current) {
      drainingRef.current = true;
      void drainModelChanges();
    }
  }

  useEffect(() => {
    const next = { ...overridesRef.current };
    let changed = false;
    for (const kind of modelKinds) {
      const entry = next[kind];
      if (entry && !entry.pending && sortedKey(entry.ids) === sortedKey(modelIds(space, kind))) {
        delete next[kind];
        changed = true;
      }
    }
    if (changed) {
      overridesRef.current = next;
      setOverrides(next);
    }
  }, [space, overrides]);

  const {
    data: models,
    isPending: modelsPending,
    isError: modelsError,
    isFetching: modelsFetching,
    refetch: refetchModels
  } = useQuery({
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

  return (
    <SettingsGroup
      title={t("space_settings_models_title")}
      description={t("space_settings_models_description")}
    >
      {modelsPending ? <LoadingState rows={3} /> : null}
      {modelsError ? (
        <SettingsLoadFailure
          title={t("space_models_load_failed")}
          retrying={modelsFetching}
          onRetry={() => void refetchModels()}
        />
      ) : null}
      {models ? (
        <>
          <SpaceModelSelect
            kind="completion"
            title={t("space_settings_chat_models")}
            description={t("space_settings_chat_models_description")}
            models={completionModels}
            selectedIds={overrides.completion?.ids ?? modelIds(space, "completion")}
            onChange={(change) => changeModels("completion", change)}
          />
          {failedKind === "completion" && (
            <Banner status="error" title={t("space_models_save_failed")} />
          )}
          <SpaceModelSelect
            kind="embedding"
            title={t("space_settings_embedding_models")}
            description={t("space_settings_embedding_models_description")}
            models={embeddingModels}
            selectedIds={overrides.embedding?.ids ?? modelIds(space, "embedding")}
            onChange={(change) => changeModels("embedding", change)}
          />
          {failedKind === "embedding" && (
            <Banner status="error" title={t("space_models_save_failed")} />
          )}
          <SpaceModelSelect
            kind="transcription"
            title={t("space_settings_transcription_models")}
            description={t("space_settings_transcription_models_description")}
            models={transcriptionModels}
            selectedIds={overrides.transcription?.ids ?? modelIds(space, "transcription")}
            onChange={(change) => changeModels("transcription", change)}
          />
          {failedKind === "transcription" && (
            <Banner status="error" title={t("space_models_save_failed")} />
          )}
        </>
      ) : null}
    </SettingsGroup>
  );
}

function ToolsSection() {
  const t = useTranslations();
  return (
    <SettingsGroup title={t("space_settings_tools_title")}>
      <McpServersSection />
    </SettingsGroup>
  );
}

function McpServersSection() {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateSpace();
  const autosave = useAutosave("mcp-servers");

  const {
    data: mcpServers,
    isPending,
    isError,
    isFetching,
    refetch
  } = useQuery(mcpServersQueryOptions(browserApi));
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

  // The selection shows each press at once and saves in order (the space's
  // saves queue), so a switch stays enabled and keeps focus while it saves;
  // the last one pressed shows it is saving.
  const [toggled, setToggled] = useState<string | null>(null);

  function toggle(id: string, on: boolean) {
    setToggled(id);
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
    <SettingsRow
      id="mcp-servers"
      title={t("mcp_servers")}
      description={t("select_mcp_servers_description")}
    >
      {isError && mcpServers ? (
        <SettingsLoadFailure
          title={t("space_mcp_servers_load_failed")}
          retrying={isFetching}
          onRetry={() => void refetch()}
        />
      ) : null}
      {isPending ? (
        <LoadingState rows={2} />
      ) : isError && !mcpServers ? (
        <SettingsLoadFailure
          title={t("space_mcp_servers_load_failed")}
          retrying={isFetching}
          onRetry={() => void refetch()}
        />
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
                  disabled={!server.is_available && !selected.has(server.id)}
                  aria-busy={(update.isPending && toggled === server.id) || undefined}
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

function SpaceCapabilitiesSection() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const update = useUpdateSpace();
  const autosave = useAutosave("capabilities");
  const selected = space.enabled_capabilities ?? [];

  return (
    <SettingsGroup title={t("capabilities")} description={t("space_capabilities_description")}>
      {CAPABILITIES.map((capability) => {
        const availability = space.available_capabilities?.find(
          (item) => item.purpose === capability.purpose
        );
        const enabled = selected.includes(capability.purpose);
        const blocked = capabilityBlockReason({
          enabled,
          spaceEnabled: true,
          available: availability?.available === true,
          modelSupportsTools: true
        });
        const hint = blocked
          ? t(readinessKey(availability?.reason ?? blocked))
          : t(capability.spaceHint);
        return (
          <div key={capability.purpose} className="flex items-center gap-3 rounded-lg border p-4">
            <capability.icon aria-hidden="true" className="text-muted-foreground size-5 shrink-0" />
            <div className="min-w-0 flex-1">
              <Label htmlFor={`space-${capability.purpose}`}>{t(capability.purpose)}</Label>
              <p className="text-muted-foreground text-sm">{hint}</p>
            </div>
            {/* Saving, it stays enabled so it keeps focus. A toggle meanwhile is
                ignored: each save sends the whole selection. */}
            <Switch
              id={`space-${capability.purpose}`}
              checked={enabled}
              disabled={!can("edit", "space") || blocked !== null}
              aria-busy={
                (update.isPending &&
                  update.variables?.enabled_capabilities?.includes(capability.purpose) !==
                    enabled) ||
                undefined
              }
              onCheckedChange={() => {
                if (update.isPending) return;
                void autosave(() =>
                  update.mutateAsync({
                    enabled_capabilities: toggleCapability(selected, capability.purpose)
                  })
                );
              }}
            />
          </div>
        );
      })}
    </SettingsGroup>
  );
}

export function SpaceSettings() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const isOrgSpace = space.organization;
  const showDanger = !isOrgSpace && can("delete", "space");
  const sections: SettingsSection[] = [
    ...(!isOrgSpace
      ? [
          { id: "general", label: t("general"), icon: SlidersHorizontal, node: <GeneralSection /> },
          {
            id: "security",
            label: t("security_and_privacy"),
            icon: ShieldCheck,
            node: <SecuritySection />
          }
        ]
      : []),
    {
      id: "models",
      label: t("space_settings_models_title"),
      icon: Bot,
      // Pending model overrides belong to one space; remount when navigating.
      node: <ModelsSection key={space.id} />
    },
    { id: "tools", label: t("space_settings_tools_title"), icon: Plug, node: <ToolsSection /> },
    ...(!isOrgSpace
      ? [
          {
            id: "capabilities",
            label: t("capabilities"),
            icon: Sparkles,
            node: <SpaceCapabilitiesSection />
          }
        ]
      : []),
    { id: "api-keys", label: t("api_keys"), icon: KeyRound, node: <SpaceApiKeysSection /> },
    ...(showDanger
      ? [{ id: "danger", label: t("danger_zone"), icon: TriangleAlert, node: <DangerSection /> }]
      : [])
  ];

  return (
    <SaveStatusProvider>
      <SectionedSettings
        navigationLabel={t("settings")}
        sections={sections}
        header={
          <PageHeader
            headingLevel={2}
            title={t("settings")}
            actions={<SaveStatusIndicator />}
            className="py-3"
          />
        }
      />
    </SaveStatusProvider>
  );
}
