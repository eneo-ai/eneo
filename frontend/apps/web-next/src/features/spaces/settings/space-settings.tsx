import { Badge } from "@astryxdesign/core/Badge";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Switch as SettingSwitch } from "@astryxdesign/core/Switch";
import { Banner } from "@astryxdesign/core/Banner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "@/lib/link";
import { useRouter } from "@/lib/navigation";
import { useLocale, useTranslations } from "use-intl";
import { useEffect, useId, useRef, useState } from "react";
import {
  Bot,
  ChevronRight,
  KeyRound,
  Plug,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TriangleAlert
} from "lucide-react";
import { ConfirmDialog, ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { IconField } from "@/components/composites/icon-field";
import { LoadingState } from "@/components/composites/loading-state";
import {
  blockingError,
  ListError,
  QueryStateBoundary,
  RefreshError
} from "@/components/composites/query-state";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import {
  SectionedSettings,
  type SettingsSection
} from "@/components/composites/sectioned-settings";
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
import { mcpServersQueryOptions, mcpServerToolsQueryOptions } from "@/features/admin/mcp/mcp";
import {
  transcriptionServiceCatalogueQueryOptions,
  type TranscriptionServiceSummary
} from "@/features/admin/models/transcription-services";
import {
  securityClassificationsQueryOptions,
  type SecurityClassification
} from "@/features/admin/security-classifications/security-classifications";
import { parseRetentionDays } from "@/features/spaces/retention-days";
import { invalidateDeletedSpace, invalidateSpacesList, type Space } from "@/features/spaces/space";
import { editorSummaries } from "@/features/spaces/editor-summaries";
import { useSpace } from "@/features/spaces/use-space";
import { PageHeader } from "@/components/composites/page-header";
import {
  selectedVisibleMcpServerCount,
  spaceMcpSelection,
  spaceMcpServerChoices,
  setSpaceMcpServer,
  setSpaceMcpTool,
  type SpaceMcpSelection,
  type SpaceMcpServerChoice
} from "./space-mcp-selection";
import {
  type SpaceSecurityImpact,
  type SpaceSecurityImpactKey,
  securityImpactRows,
  securityImpactTotal
} from "./security-impact";
import { SpaceModelSelect, type ModelKind, type ModelSelectionChange } from "./space-model-select";
import { SpaceSpeakerServices } from "./space-speaker-services";
import { SpaceDeletionHint } from "@/features/spaces/list/delete-space-dialog";
import { useSectionHeadingLevels } from "@/features/spaces/frame/space-frame";

type SpaceUpdate = Schema<"PartialUpdateSpaceRequest">;
type SpaceUpdateRequest = SpaceUpdate | ((currentSpace: Space) => SpaceUpdate);
const SECURITY_IMPACT_LABEL_KEYS: Record<SpaceSecurityImpactKey, string> = {
  assistants: "assistants",
  group_chats: "group_chats",
  apps: "apps",
  services: "services",
  completion_models: "completion_models",
  embedding_models: "embedding_models",
  transcription_models: "transcription_models",
  mcp_servers: "mcp_servers",
  capabilities: "capabilities"
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

function useUpdateSpace() {
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();

  // Feedback is owned by the caller's autosave wrapper (useAutosave); this
  // mutation writes the server's full response to the detail cache.
  return useMutation({
    scope: { id: `space:${space.id}` },
    mutationFn: (request: SpaceUpdateRequest) => {
      let body: SpaceUpdate;
      if (typeof request === "function") {
        // A scoped mutation starts after earlier space writes have settled.
        const current = queryClient.getQueryData<Space>(["spaces", routeId]);
        if (!current) throw new Error("Space must be loaded before updating its settings");
        body = request(current);
      } else body = request;
      return unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/", {
          params: { path: { id: space.id } },
          body
        })
      );
    },
    onSuccess: async (saved) => {
      // PATCH returns the authoritative full space. An older GET must not
      // replace it while the detail query is being refreshed.
      await queryClient.cancelQueries({ queryKey: ["spaces", routeId], exact: true });
      queryClient.setQueryData(["spaces", routeId], saved);
      void invalidateSpacesList(queryClient);
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
  const { space, can } = useSpace();
  const queryClient = useQueryClient();
  const update = useUpdateSpace();
  const autosave = useAutosave("security");
  const [loadingImpact, setLoadingImpact] = useState(false);
  const impactRequest = useRef<AbortController | null>(null);
  const [pendingImpact, setPendingImpact] = useState<{
    classification: SecurityClassification | null;
    impact: SpaceSecurityImpact | null;
  } | null>(null);
  useEffect(() => () => impactRequest.current?.abort(), []);

  const securityQuery = useQuery(securityClassificationsQueryOptions(browserApi));
  const security = securityQuery.data;
  const NONE = "__none__";
  const currentClassificationId = space.security_classification?.id ?? NONE;

  async function saveSecurityClassification(classification: SecurityClassification | null) {
    return autosave(async () => {
      const saved = await update.mutateAsync({
        security_classification: classification ? { id: classification.id } : null
      });
      await queryClient.invalidateQueries({ queryKey: ["ai-models", space.id], exact: true });
      return saved;
    });
  }

  async function requestSecurityClassificationChange(value: string) {
    if (
      !can("edit", "space") ||
      value === currentClassificationId ||
      loadingImpact ||
      update.isPending
    )
      return;
    const classification =
      security?.security_classifications.find((item) => item.id === value) ?? null;
    if (value === NONE) {
      setPendingImpact({ classification: null, impact: null });
      return;
    }
    if (!classification) return;
    const controller = new AbortController();
    impactRequest.current?.abort();
    impactRequest.current = controller;
    setLoadingImpact(true);
    try {
      const impact = await unwrap(
        browserApi.GET(
          "/api/v1/spaces/{id}/security_classification/{security_classification_id}/impact-analysis/",
          {
            params: { path: { id: space.id, security_classification_id: classification.id } },
            signal: controller.signal
          }
        )
      );
      if (!controller.signal.aborted) setPendingImpact({ classification, impact });
    } catch (error) {
      if (!controller.signal.aborted) toastApiError(error, t);
    } finally {
      if (impactRequest.current === controller) {
        impactRequest.current = null;
        setLoadingImpact(false);
      }
    }
  }

  async function confirmSecurityClassificationChange() {
    if (!pendingImpact || update.isPending || !can("edit", "space")) return;
    const result = await saveSecurityClassification(pendingImpact.classification);
    if (result !== undefined) setPendingImpact(null);
  }

  const pendingImpactRows = pendingImpact ? securityImpactRows(pendingImpact.impact) : [];
  const pendingImpactTotal = pendingImpact ? securityImpactTotal(pendingImpact.impact) : 0;

  return (
    <SettingsGroup title={t("security_and_privacy")}>
      <RefreshError queries={[securityQuery]} />
      {blockingError(securityQuery) ? (
        <ListError
          error={securityQuery.error}
          title={t("space_security_load_failed")}
          isRetrying={securityQuery.isFetching}
          onRetry={() => void securityQuery.refetch()}
        />
      ) : securityQuery.isPending ? (
        <LoadingState rows={1} />
      ) : null}
      {security?.security_enabled && (
        <SettingsRow
          title={t("security_classification")}
          description={t("security_classification_description")}
        >
          <Select
            value={currentClassificationId}
            disabled={!can("edit", "space") || update.isPending || loadingImpact}
            onValueChange={(value) => void requestSecurityClassificationChange(value)}
          >
            <SelectTrigger className="w-64" aria-label={t("security_classification")}>
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
          <ConfirmDialogControlled
            open={pendingImpact !== null}
            onOpenChange={(open) => !open && setPendingImpact(null)}
            title={t("migration_impact")}
            description={t("migration_impact_title", { count: pendingImpactTotal })}
            confirmLabel={update.isPending ? t("saving") : t("confirm")}
            variant="default"
            pending={update.isPending}
            onConfirm={() => void confirmSecurityClassificationChange()}
          >
            <div className="flex flex-col gap-3">
              <p className="text-sm">
                <span className="font-medium">{t("security_classification")}: </span>
                {pendingImpact?.classification?.name ?? t("none")}
              </p>
              <p className="text-sm font-medium">{t("affected_resources")}</p>
              {pendingImpactRows.length === 0 ? (
                <p className="text-ax-text-secondary text-sm">{t("none")}</p>
              ) : (
                <ul className="flex flex-col gap-3 text-sm">
                  {pendingImpactRows.map((row) => (
                    <li key={row.key}>
                      <p className="font-medium">
                        {t(SECURITY_IMPACT_LABEL_KEYS[row.key])}{" "}
                        <span className="tabular-nums">({row.count})</span>
                      </p>
                      <ul className="text-ax-text-secondary ms-5 list-disc">
                        {row.names.map((name, index) => (
                          <li key={`${name}-${index}`} className="break-words">
                            {row.key === "capabilities" ? t(name) : name}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </ConfirmDialogControlled>
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

  const days = useAutosaveField({
    key: "retention-days",
    value: space.data_retention_days?.toString() ?? "",
    save: (value) => update.mutateAsync({ data_retention_days: parseRetentionDays(value) }),
    // Empty means "keep forever".
    validate: (value) => parseRetentionDays(value) !== undefined
  });
  const daysProblem =
    daysVisited && parseRetentionDays(days.value) === undefined
      ? t("space_retention_invalid")
      : null;

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

  const modelsQuery = useQuery({
    queryKey: ["ai-models", space.id],
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/ai-models/", { params: { query: { space_id: space.id } } }))
  });
  const models = modelsQuery.data;

  const completionModels = (models?.completion_models ?? []).filter(
    (model) => model.is_org_enabled && !model.migrated_to_model_id
  );
  const embeddingModels = (models?.embedding_models ?? []).filter((model) => model.is_org_enabled);
  const transcriptionModels = (models?.transcription_models ?? []).filter(
    (model) => model.is_org_enabled && !model.migrated_to_model_id
  );

  return (
    <SettingsGroup
      title={t("space_settings_models_title")}
      description={t("space_settings_models_description")}
    >
      <RefreshError queries={[modelsQuery]} />
      {blockingError(modelsQuery) ? (
        <ListError
          error={modelsQuery.error}
          title={t("space_models_load_failed")}
          isRetrying={modelsQuery.isFetching}
          onRetry={() => void modelsQuery.refetch()}
        />
      ) : modelsQuery.isPending ? (
        <LoadingState rows={3} />
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
            <Banner role="alert" status="error" title={t("space_models_save_failed")} />
          )}
          <SpaceModelSelect
            kind="embedding"
            isOrganization={space.organization}
            title={t("space_settings_embedding_models")}
            description={t("space_settings_embedding_models_description")}
            models={embeddingModels}
            selectedIds={overrides.embedding?.ids ?? modelIds(space, "embedding")}
            onChange={(change) => changeModels("embedding", change)}
          />
          {failedKind === "embedding" && (
            <Banner role="alert" status="error" title={t("space_models_save_failed")} />
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
            <Banner role="alert" status="error" title={t("space_models_save_failed")} />
          )}
        </>
      ) : null}
      <SpeakerServicesRow />
    </SettingsGroup>
  );
}

/**
 * The speaker identification services granted to the space, through the
 * space's one save path: each switch sends the whole list, built from the
 * space as the previous save left it, one change at a time. Flows in the
 * space read the same grants from the space (`transcription_services`).
 */
function SpeakerServicesRow() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const update = useUpdateSpace();
  const autosave = useAutosave("speaker-services");
  const catalogue = useQuery(transcriptionServiceCatalogueQueryOptions(browserApi));
  const security = useQuery(securityClassificationsQueryOptions(browserApi));
  const [savingId, setSavingId] = useState<string | null>(null);
  // Read by a second press before the first one's render.
  const savingRef = useRef(false);

  async function toggle(service: TranscriptionServiceSummary, grant: boolean) {
    if (savingRef.current) return;
    savingRef.current = true;
    setSavingId(service.id);
    await autosave(() =>
      update.mutateAsync((latest) => {
        const current = latest.transcription_services;
        if (!current) throw new Error(t("speaker_service_space_load_failed"));
        const ids = current.map((granted) => granted.id).filter((id) => id !== service.id);
        return {
          transcription_services: (grant ? [...ids, service.id] : ids).map((id) => ({ id }))
        };
      })
    );
    savingRef.current = false;
    setSavingId(null);
  }

  return (
    <SettingsRow
      id="speaker-services"
      title={t("speaker_identification")}
      description={t("speaker_service_space_description")}
    >
      <QueryStateBoundary
        query={catalogue}
        rows={2}
        errorTitle={t("speaker_service_space_load_failed")}
      >
        {(services) => (
          <SpaceSpeakerServices
            services={services}
            links={space.transcription_services}
            spaceClassification={space.security_classification}
            // Until the setting is read (its own section reports a failure),
            // a classified space offers only what meets its class.
            securityEnabled={security.data?.security_enabled ?? true}
            canEdit={can("edit", "space")}
            savingId={savingId}
            onToggle={(service, grant) => void toggle(service, grant)}
          />
        )}
      </QueryStateBoundary>
    </SettingsRow>
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

type SpaceMcpChange =
  | {
      kind: "server";
      server: Pick<SpaceMcpServerChoice, "id" | "name" | "tools">;
      enabled: boolean;
    }
  | { kind: "tool"; serverId: string; toolId: string; enabled: boolean };

function McpServersSection() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const queryClient = useQueryClient();
  const update = useUpdateSpace();
  const autosave = useAutosave("mcp-servers");
  const servers = useQuery(mcpServersQueryOptions(browserApi));
  const confirmed = spaceMcpSelection(space.mcp_servers ?? []);
  const [optimistic, setOptimistic] = useState<SpaceMcpSelection | null>(null);
  const selection = optimistic ?? confirmed;
  const selectionRef = useRef<SpaceMcpSelection | null>(null);
  const version = useRef(0);

  function save(change: SpaceMcpChange) {
    const cached = queryClient.getQueryData<Space>(["spaces", routeId]);
    if (!cached) return;
    const current = selectionRef.current ?? spaceMcpSelection(cached.mcp_servers ?? []);
    if (change.kind === "tool" && !current.serverIds.includes(change.serverId)) return;
    const applyChange = (selection: SpaceMcpSelection) =>
      change.kind === "server"
        ? setSpaceMcpServer(selection, change.server, change.enabled)
        : setSpaceMcpTool(selection, change.toolId, change.enabled);
    const next = applyChange(current);
    const attempt = ++version.current;
    selectionRef.current = next;
    setOptimistic(next);
    void autosave(() =>
      update.mutateAsync((currentSpace) => {
        const next = applyChange(spaceMcpSelection(currentSpace.mcp_servers ?? []));
        return change.kind === "tool"
          ? { mcp_tools: next.tools }
          : {
              mcp_servers: next.serverIds.map((id) => ({ id })),
              ...(change.enabled ? { mcp_tools: next.tools } : {})
            };
      })
    ).then(() => {
      // A failed queued intent must recover the last confirmed response,
      // rather than a previous optimistic intent that may also have failed.
      if (version.current === attempt) {
        selectionRef.current = null;
        setOptimistic(null);
      }
    });
  }

  const candidates = spaceMcpServerChoices(servers.data ?? [], space.mcp_servers ?? []);
  const activeCount = selectedVisibleMcpServerCount(candidates, selection.serverIds);
  const canEdit = can("edit", "space");

  return (
    <SettingsRow
      id="mcp-servers"
      title={t("mcp_servers")}
      description={t("select_mcp_servers_description")}
    >
      <RefreshError queries={[servers]} />
      {blockingError(servers) ? (
        <ListError
          error={servers.error}
          title={t("space_mcp_servers_load_failed")}
          isRetrying={servers.isFetching}
          onRetry={() => void servers.refetch()}
        />
      ) : servers.isPending ? (
        <LoadingState rows={2} />
      ) : candidates.length === 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-muted-foreground text-sm">{t("enable_mcp_servers_in_admin")}</p>
          <Button asChild variant="outline" size="sm">
            <Link href="/admin/tools?tab=mcp-servers">{t("mcp_servers")}</Link>
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2" aria-busy={optimistic !== null || undefined}>
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
            {candidates.map((server) => {
              const reason = !server.is_available
                ? t(readinessKey(server.readiness_reason))
                : space.security_classification &&
                    (!server.security_classification ||
                      server.security_classification.security_level <
                        space.security_classification.security_level)
                  ? t("mcp_server_does_not_meet_security_classification")
                  : null;
              return (
                <SpaceMcpServerRow
                  key={server.id}
                  server={server}
                  selected={selection.serverIds.includes(server.id)}
                  settings={selection.tools}
                  canEdit={canEdit}
                  reason={reason}
                  onServerChange={(enabled, tools) => {
                    if (!canEdit || (enabled && reason)) return;
                    save({
                      kind: "server",
                      server: { id: server.id, name: server.name, tools },
                      enabled
                    });
                  }}
                  onToolChange={(id, enabled) => {
                    if (!canEdit || (enabled && reason)) return;
                    save({ kind: "tool", serverId: server.id, toolId: id, enabled });
                  }}
                />
              );
            })}
          </fieldset>
        </div>
      )}
    </SettingsRow>
  );
}

function SpaceMcpServerRow({
  server,
  selected,
  settings,
  canEdit,
  reason,
  onServerChange,
  onToolChange
}: {
  server: SpaceMcpServerChoice;
  selected: boolean;
  settings: Schema<"MCPToolSetting">[];
  canEdit: boolean;
  reason: string | null;
  onServerChange: (enabled: boolean, tools: SpaceMcpServerChoice["tools"]) => void;
  onToolChange: (id: string, enabled: boolean) => void;
}) {
  const t = useTranslations();
  const id = useId();
  const [expanded, setExpanded] = useState(false);
  const mounted = useRef(true);
  const readingForAddition = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const tools = useQuery({
    ...mcpServerToolsQueryOptions(browserApi, server.id),
    enabled: selected && expanded && server.needsTools
  });
  const availableTools = [
    ...new Map([...server.tools, ...(tools.data ?? [])].map((tool) => [tool.id, tool])).values()
  ];
  const disabledReason = !canEdit ? t("tools_readiness_permission") : !selected ? reason : null;
  const hasTools = selected && (availableTools.length > 0 || server.needsTools);

  async function changeServer(enabled: boolean) {
    if (readingForAddition.current || tools.isFetching || !canEdit || (enabled && reason)) return;
    if (!enabled || !server.needsTools || tools.data !== undefined) {
      onServerChange(enabled, availableTools);
      return;
    }
    readingForAddition.current = true;
    try {
      const result = await tools.refetch();
      if (mounted.current && !result.isError && result.data) {
        onServerChange(true, result.data);
      }
    } finally {
      readingForAddition.current = false;
    }
  }

  return (
    <div className="border-border rounded-lg border p-3">
      <div className="flex items-start gap-2">
        <IconButton
          label={t("mcp_tools_for_server_aria", { name: server.name })}
          tooltip={t(expanded ? "governance_mcp_hide_tools" : "governance_mcp_show_tools")}
          icon={
            <ChevronRight aria-hidden="true" className={expanded ? "size-4 rotate-90" : "size-4"} />
          }
          variant="ghost"
          aria-expanded={expanded}
          aria-controls={hasTools ? `${id}-tools` : undefined}
          isDisabled={!hasTools}
          onClick={() => setExpanded((open) => !open)}
        />
        <div className="min-w-0 flex-1 space-y-2">
          <SettingSwitch
            label={server.name}
            labelPosition="start"
            labelSpacing="spread"
            width="100%"
            value={selected}
            onChange={(enabled) => void changeServer(enabled)}
            isDisabled={disabledReason !== null}
            disabledMessage={disabledReason ?? undefined}
            aria-describedby={reason ? `${id}-reason` : undefined}
            aria-busy={tools.isFetching || undefined}
          />
          {server.description && (
            <p className="text-muted-foreground text-sm">{server.description}</p>
          )}
          {server.tags && server.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {server.tags.map((tag) => (
                <Badge key={tag} label={tag} />
              ))}
            </div>
          )}
          {reason && (
            <p id={`${id}-reason`} className="text-muted-foreground text-sm">
              {reason}
            </p>
          )}
          {!expanded && tools.isFetching && tools.data === undefined && <LoadingState rows={1} />}
          <RefreshError queries={[tools]} />
          {blockingError(tools) && (
            <ListError
              error={tools.error}
              isRetrying={tools.isFetching}
              onRetry={() => void tools.refetch()}
            />
          )}
        </div>
      </div>
      {expanded && hasTools && (
        <fieldset
          id={`${id}-tools`}
          aria-label={t("mcp_tools_for_server_aria", { name: server.name })}
          className="border-border mt-3 space-y-3 border-t pt-3"
        >
          {tools.isFetching && tools.data === undefined && <LoadingState rows={1} />}
          {availableTools.map((tool) => {
            const enabled =
              settings.find((setting) => setting.tool_id === tool.id)?.is_enabled ?? false;
            const blocked = !canEdit
              ? t("tools_readiness_permission")
              : !enabled
                ? (reason ?? (tool.removed_from_remote ? t("not_available") : null))
                : null;
            return (
              <div key={tool.id} className="space-y-1">
                <SettingSwitch
                  label={tool.title || tool.name}
                  labelPosition="start"
                  labelSpacing="spread"
                  width="100%"
                  value={enabled}
                  isDisabled={blocked !== null}
                  disabledMessage={blocked ?? undefined}
                  onChange={(next) => {
                    if (!blocked) onToolChange(tool.id, next);
                  }}
                />
                {tool.description && (
                  <p className="text-muted-foreground text-sm">{tool.description}</p>
                )}
                {tool.removed_from_remote && (
                  <p className="text-muted-foreground text-sm">{t("not_available")}</p>
                )}
              </div>
            );
          })}
        </fieldset>
      )}
    </div>
  );
}

function DangerSection() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const router = useRouter();
  const queryClient = useQueryClient();

  const deleteSpace = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/spaces/{id}/", { params: { path: { id: space.id } } })),
    onSuccess: () => {
      void invalidateDeletedSpace(queryClient, routeId);
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
          >
            {deleteSpace.isPending && <SpaceDeletionHint />}
          </ConfirmDialog>
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
                  typeof update.variables !== "function" &&
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
  const levels = useSectionHeadingLevels();
  const { space, can } = useSpace();
  const summary = editorSummaries(t);
  const isOrgSpace = space.organization;
  const showDanger = !isOrgSpace && can("delete", "space");
  // A phone's index lists the sections under these headings (decision 21).
  const own = t("space_settings_group_space");
  const model = t("editor_group_model");
  const access = t("editor_group_access");
  const sections: SettingsSection[] = [
    ...(!isOrgSpace
      ? [
          {
            id: "general",
            label: t("general"),
            icon: SlidersHorizontal,
            group: own,
            summary: summary.description(space.description),
            node: <GeneralSection />
          },
          {
            id: "security",
            label: t("security_and_privacy"),
            icon: ShieldCheck,
            group: own,
            // No limit set says nothing: "Ytans gallring" is for what lives in a space.
            summary: space.data_retention_days
              ? summary.retention(space.data_retention_days)
              : undefined,
            node: <SecuritySection />
          }
        ]
      : []),
    {
      id: "models",
      label: t("space_settings_models_title"),
      icon: Bot,
      group: model,
      // Pending model overrides belong to one space; remount when navigating.
      node: <ModelsSection key={space.id} />
    },
    {
      id: "tools",
      label: t("space_settings_tools_title"),
      icon: Plug,
      group: model,
      node: <ToolsSection />
    },
    {
      id: "capabilities",
      label: t("capabilities"),
      icon: Sparkles,
      group: model,
      node: <SpaceCapabilitiesSection />
    },
    {
      id: "api-keys",
      label: t("api_keys"),
      icon: KeyRound,
      group: access,
      node: <SpaceApiKeysSection />
    },
    ...(showDanger
      ? [
          {
            id: "danger",
            label: t("danger_zone"),
            icon: TriangleAlert,
            // No group: deleting the space is not an access setting, and it stands apart.
            node: <DangerSection />
          }
        ]
      : [])
  ];

  return (
    <SaveStatusProvider>
      <SectionedSettings
        navigationLabel={t("settings")}
        sections={sections}
        // The space's own page bar sits above the index (a phone's settings are a page of the
        // space, not a pushed screen), so the index has none; a section has one back to it.
        phone={{ title: t("settings") }}
        // Under the space's header: on its line, like the space's other pages.
        isFramed
        header={
          <PageHeader
            headingLevel={levels.title}
            title={t("settings")}
            actions={<SaveStatusIndicator />}
            className="py-3"
          />
        }
      />
    </SaveStatusProvider>
  );
}
