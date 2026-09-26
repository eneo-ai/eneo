"use client";

import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useSetSaveStatus } from "@/components/composites/save-status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { useSpace } from "@/features/spaces/use-space";
import {
  candidateRevisionId,
  candidateRevisionNumber,
  getSkillPreview,
  getSkillPreviewForRevision,
  isAttachable,
  loadSkillBindingCatalog,
  type SkillCandidate
} from "./skill-binding-catalog";
import {
  activateBinding,
  appBindingPayload,
  appendBinding,
  bindingsFromSummaries,
  moveBinding,
  removeBinding,
  reviseBinding,
  type Binding,
  type BindingSummary
} from "./skill-bindings";
import { SkillForm } from "./skill-form";
import { skillQueryKey } from "./skill-revisions";

type ResourceProps = {
  resource: "assistant" | "app";
  resourceId: string;
  canEdit: boolean;
  save: (bindings: Binding[]) => Promise<unknown>;
};

type EditorProps = {
  resource: "assistant" | "app" | "personal_chat";
  resourceId?: string;
  spaceId: string;
  organizationSpace: boolean;
  canEdit: boolean;
  canCreate: boolean;
  save?: (bindings: Binding[]) => Promise<unknown>;
  bindings?: Binding[];
  summaries?: BindingSummary[];
  onChange?: (bindings: Binding[]) => void;
  selectiveActivationEnabled?: boolean;
};

type Preview = Awaited<ReturnType<typeof getSkillPreview>>;
type DraftSnapshot = { source: unknown; baseline: Binding[]; draft: Binding[] };

function runtimeMessage(
  runtime: Schema<"AssistantSkillRuntimeSummary"> | null | undefined,
  t: ReturnType<typeof useTranslations>
) {
  if (!runtime) return t("skills_activation_runtime_no_model");
  switch (runtime.fallback_reason) {
    case "model_lacks_tool_calling":
      return t("skills_activation_runtime_model_lacks_tools");
    case "catalog_budget_exceeded":
      return t("skills_activation_runtime_catalog_budget");
    case "token_measurement_unavailable":
      return t("skills_activation_runtime_measurement_unavailable");
    case "selective_activation_disabled":
      return t("skills_activation_runtime_disabled");
    default:
      return t(
        runtime.effective_mode === "selective"
          ? "skills_activation_runtime_selective"
          : runtime.effective_mode === "always_only"
            ? "skills_activation_runtime_always_only"
            : "skills_activation_runtime_eager"
      );
  }
}

/** Resource adapter: keeps space permissions and resource save ownership outside the editor. */
export function SkillBindingsSection(props: ResourceProps) {
  const { space, can } = useSpace();
  return (
    <SkillBindingsEditor
      {...props}
      spaceId={space.id}
      organizationSpace={space.organization}
      canCreate={can("create", "skill") && !space.organization}
    />
  );
}

/** Shared ordered, version-pinned editor, also used by the Personal Chat policy draft. */
export function SkillBindingsEditor({
  resource,
  resourceId = "",
  spaceId,
  organizationSpace,
  canEdit,
  canCreate,
  save,
  bindings,
  summaries: controlledSummaries,
  onChange,
  selectiveActivationEnabled
}: EditorProps) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const setSaveStatus = useSetSaveStatus();
  const key = [resource, resourceId, "skills"] as const;
  const configuration = useQuery({
    queryKey: key,
    queryFn: async () => {
      if (resource === "personal_chat") return { bindings: [], runtime: null };
      if (resource === "assistant")
        return unwrap(
          browserApi.GET(
            "/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/configuration/",
            { params: { path: { space_id: spaceId, assistant_id: resourceId } } }
          )
        );
      const bindings = await unwrap(
        browserApi.GET("/api/v1/spaces/{space_id}/apps/{app_id}/skills/", {
          params: { path: { space_id: spaceId, app_id: resourceId } }
        })
      );
      return { bindings, runtime: null };
    },
    enabled: resource !== "personal_chat",
    retry: false
  });
  const summaries: BindingSummary[] =
    resource === "personal_chat"
      ? (controlledSummaries ?? [])
      : (configuration.data?.bindings ?? []);
  const runtime = configuration.data?.runtime ?? null;
  const loaded = useMemo(
    () => bindingsFromSummaries(configuration.data?.bindings ?? []),
    [configuration.data]
  );
  const [editing, setEditing] = useState<DraftSnapshot | null>(null);
  const editingDirty =
    editing !== null && JSON.stringify(editing.draft) !== JSON.stringify(editing.baseline);
  const activeEdit = editing !== null && (editing.source === configuration.data || editingDirty);
  const baseline = activeEdit ? editing.baseline : loaded;
  const draft =
    resource === "personal_chat" ? (bindings ?? []) : activeEdit ? editing.draft : loaded;
  const dirty = resource !== "personal_chat" && JSON.stringify(draft) !== JSON.stringify(baseline);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [showPicker, setShowPicker] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [created, setCreated] = useState<SkillCandidate[]>([]);
  const [previewCandidate, setPreviewCandidate] = useState<SkillCandidate | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createDirty, setCreateDirty] = useState(false);
  const [upgradeBusy, setUpgradeBusy] = useState<string | null>(null);
  const [upgradeError, setUpgradeError] = useState<string | null>(null);
  const [revisionMetadata, setRevisionMetadata] = useState<Preview[]>([]);

  function setDraft(next: Binding[] | ((current: Binding[]) => Binding[])) {
    // What was announced (saved, nothing to save) no longer holds.
    setAnnouncement("");
    if (resource === "personal_chat") {
      onChange?.(typeof next === "function" ? next(bindings ?? []) : next);
      return;
    }
    setEditing((current) => {
      const currentDirty =
        current !== null && JSON.stringify(current.draft) !== JSON.stringify(current.baseline);
      const active = current !== null && (current.source === configuration.data || currentDirty);
      const currentBaseline = active ? current.baseline : loaded;
      const currentDraft = active ? current.draft : loaded;
      return {
        source: configuration.data,
        baseline: currentBaseline,
        draft: typeof next === "function" ? next(currentDraft) : next
      };
    });
  }

  useEffect(() => {
    if (!setSaveStatus) return;
    setSaveStatus(
      "skills",
      resource === "personal_chat"
        ? null
        : saving
          ? "saving"
          : saveError
            ? "error"
            : dirty
              ? "dirty"
              : null
    );
    return () => setSaveStatus("skills", null);
  }, [dirty, resource, saveError, saving, setSaveStatus]);

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const catalogue = useInfiniteQuery({
    queryKey: ["skill-binding-catalogue", spaceId, search],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      loadSkillBindingCatalog({
        spaceId,
        organizationSpace,
        cursor: pageParam,
        search
      }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: showPicker,
    retry: false
  });
  const catalogItems = useMemo(() => {
    const byId = new Map<string, SkillCandidate>();
    for (const skill of catalogue.data?.pages.flatMap((page) => page.items) ?? [])
      byId.set(skill.id, skill);
    for (const skill of created) byId.set(skill.id, skill);
    return [...byId.values()];
  }, [catalogue.data, created]);
  const choices = catalogItems.filter(
    (skill) => isAttachable(skill) && !draft.some((binding) => binding.skill_id === skill.id)
  );
  const canChooseOnDemand =
    resource === "personal_chat"
      ? selectiveActivationEnabled === true
      : resource === "assistant" && runtime?.fallback_reason === null;

  async function openPreview(skill: SkillCandidate) {
    setPreviewCandidate(skill);
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      setPreview(await getSkillPreview(spaceId, skill));
    } catch {
      setPreviewError(t("skills_preview_load_error"));
    } finally {
      setPreviewLoading(false);
    }
  }

  function attachPreview() {
    if (
      !previewCandidate ||
      !preview ||
      preview.revisionId !== candidateRevisionId(previewCandidate)
    )
      return;
    setDraft((value) => appendBinding(value, previewCandidate, resource !== "app"));
    setAnnouncement(t("skills_added_to_draft_announcement", { name: preview.displayName }));
    setPreviewCandidate(null);
    setPreview(null);
    setShowPicker(false);
  }

  async function upgradeToLatest(summary: BindingSummary, revisionId: string) {
    setUpgradeBusy(summary.skill_id);
    setUpgradeError(null);
    try {
      const exact = await getSkillPreviewForRevision(spaceId, {
        id: summary.skill_id,
        source: summary.source,
        revisionId
      });
      setRevisionMetadata((value) => [...value.filter((item) => item.id !== exact.id), exact]);
      setDraft((value) => reviseBinding(value, summary.skill_id, exact.revisionId));
      setAnnouncement(
        t("skills_revision_upgraded_announcement", {
          name: summary.display_name,
          revision: String(exact.revisionNumber)
        })
      );
    } catch {
      setUpgradeError(t("skills_preview_load_error"));
    } finally {
      setUpgradeBusy(null);
    }
  }

  // Save and Discard stay enabled, so they keep focus: busy, a second press
  // is ignored; with nothing changed they say so.
  async function saveDraft() {
    if (saving || !save) return;
    if (!dirty) {
      setAnnouncement(t("form_nothing_to_save"));
      return;
    }
    setSaving(true);
    setSaveError(null);
    const submitted = draft.map((binding) => ({ ...binding }));
    try {
      await save(resource === "app" ? appBindingPayload(submitted) : submitted);
      setEditing({ source: configuration.data, baseline: submitted, draft: submitted });
      setAnnouncement(t("skills_bindings_saved"));
      void queryClient.invalidateQueries({ queryKey: key });
    } catch (cause) {
      setSaveError(getErrorMessage(cause, t));
    } finally {
      setSaving(false);
    }
  }

  function discardDraft() {
    setAnnouncement(t(dirty ? "form_changes_discarded" : "form_nothing_to_discard"));
    setEditing(null);
    setSaveError(null);
  }

  async function createSkill(value: Schema<"SkillCreateRequest">) {
    const skill = await unwrap(
      browserApi.POST("/api/v1/spaces/{space_id}/skills/", {
        params: { path: { space_id: spaceId } },
        body: value
      })
    );
    const candidate = { ...skill, source: "space" as const };
    setCreated((current) => [...current.filter((item) => item.id !== skill.id), candidate]);
    setDraft((current) => appendBinding(current, candidate, resource !== "app"));
    setCreateDirty(false);
    setCreateOpen(false);
    setAnnouncement(
      t("skills_created_and_added_to_draft_announcement", { name: skill.display_name })
    );
    void queryClient.invalidateQueries({
      queryKey: skillQueryKey({ type: "space", spaceId })
    });
  }

  if (resource !== "personal_chat" && configuration.isPending)
    return (
      <SettingsGroup title={t("skills")}>
        <p role="status">{t("loading")}</p>
      </SettingsGroup>
    );
  if (resource !== "personal_chat" && configuration.isError)
    return (
      <SettingsGroup title={t("skills")}>
        <Alert variant="destructive" role="alert">
          <AlertTitle>{t("request_failed")}</AlertTitle>
          <AlertDescription>
            <Button variant="outline" onClick={() => void configuration.refetch()}>
              {t("retry")}
            </Button>
          </AlertDescription>
        </Alert>
      </SettingsGroup>
    );

  return (
    <SettingsGroup
      title={t(resource === "personal_chat" ? "governance_skills_heading" : "skills")}
      description={t(
        resource === "personal_chat"
          ? "governance_skills_section_description"
          : "skills_editor_description"
      )}
      headerEnd={
        <Badge variant="outline">
          {t("skills_binding_count", { count: String(draft.length) })}
        </Badge>
      }
    >
      <p className="text-muted-foreground text-sm">
        {t(
          resource === "personal_chat"
            ? "skills_binding_personal_chat_draft_description"
            : resource === "assistant"
              ? "skills_binding_assistant_draft_description"
              : "skills_binding_draft_description"
        )}
      </p>
      {resource === "personal_chat" && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-muted-foreground text-sm">
            {t("governance_skills_scope_description")}
          </p>
          <Button asChild variant="outline">
            <Link href="/spaces/organization/skills">{t("governance_manage_skills_action")}</Link>
          </Button>
        </div>
      )}
      {resource === "assistant" && (
        <Alert role="status">
          <AlertTitle>{runtimeMessage(runtime, t)}</AlertTitle>
          <AlertDescription>
            {t("skills_activation_runtime_saved_hint")}
            {runtime && (
              <span className="mt-1 block">
                {t("skills_activation_runtime_tokens", {
                  used: String(runtime.skill_context_tokens),
                  limit: String(runtime.skill_context_token_limit)
                })}
              </span>
            )}
          </AlertDescription>
        </Alert>
      )}
      {resource === "personal_chat" && (
        <Alert role="status">
          <AlertTitle>
            {t(
              selectiveActivationEnabled
                ? "skills_activation_runtime_policy_selective"
                : "skills_activation_runtime_disabled"
            )}
          </AlertTitle>
          <AlertDescription>
            {t("skills_activation_runtime_policy_validation_hint")}
          </AlertDescription>
        </Alert>
      )}
      {upgradeError && (
        <p role="alert" className="text-destructive text-sm">
          {upgradeError}
        </p>
      )}
      {draft.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("skills_no_bindings")}</p>
      ) : (
        <ol className="divide-y rounded-lg border" aria-label={t("skills_binding_order_label")}>
          {draft.map((binding, index) => {
            const summary = summaries.find((item) => item.skill_id === binding.skill_id);
            const candidate = catalogItems.find((item) => item.id === binding.skill_id);
            const metadata = revisionMetadata.find(
              (item) =>
                item.id === binding.skill_id && item.revisionId === binding.skill_revision_id
            );
            const name =
              metadata?.displayName ??
              (summary?.skill_revision_id === binding.skill_revision_id
                ? summary.display_name
                : undefined) ??
              candidate?.display_name ??
              summary?.display_name ??
              t("skills_unknown_skill");
            const description =
              metadata?.description ?? summary?.description ?? candidate?.description;
            const pinnedNumber =
              metadata?.revisionNumber ??
              (summary?.skill_revision_id === binding.skill_revision_id
                ? summary.revision_number
                : candidate && candidateRevisionId(candidate) === binding.skill_revision_id
                  ? candidateRevisionNumber(candidate)
                  : undefined);
            const attachableId =
              summary?.attachable_revision_id ??
              (candidate ? candidateRevisionId(candidate) : null);
            const attachableNumber =
              summary?.attachable_revision_number ??
              (candidate ? candidateRevisionNumber(candidate) : null);
            const blocked = summary?.execution_blocked ?? false;
            const active = summary?.is_active ?? (candidate ? isAttachable(candidate) : true);
            return (
              <li
                key={binding.skill_id}
                className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start"
              >
                <Badge variant="outline" className="w-7 justify-center">
                  {index + 1}
                </Badge>
                <div className="min-w-0 flex-1 space-y-2">
                  <div>
                    <p className="font-medium">{name}</p>
                    {description && <p className="text-muted-foreground text-sm">{description}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {pinnedNumber !== undefined && (
                      <Badge variant="outline">
                        {t("skills_revision_label", { revision: String(pinnedNumber) })}
                      </Badge>
                    )}
                    {blocked ? (
                      <Badge variant="destructive">{t("skills_execution_blocked_status")}</Badge>
                    ) : !active ? (
                      <Badge variant="outline">{t("skills_unavailable_status")}</Badge>
                    ) : null}
                    {attachableId &&
                      attachableId !== binding.skill_revision_id &&
                      attachableNumber !== null &&
                      !blocked && (
                        <Badge variant="secondary">
                          {t("skills_newer_revision_available", {
                            revision: String(attachableNumber)
                          })}
                        </Badge>
                      )}
                  </div>
                  {blocked && (
                    <p className="text-muted-foreground text-xs">
                      {t("skills_execution_blocked_binding_explanation")}
                    </p>
                  )}
                  {!active && !blocked && (
                    <p className="text-muted-foreground text-xs">
                      {t("skills_unavailable_binding_explanation")}
                    </p>
                  )}
                  {resource !== "app" && (
                    <label className="flex max-w-xs flex-col gap-1 text-sm">
                      {t("skills_activation_mode_label", { name })}
                      <select
                        className="border-input bg-background h-9 rounded-md border px-2"
                        value={binding.activation_mode ?? "always"}
                        disabled={
                          !canEdit ||
                          blocked ||
                          (!canChooseOnDemand && (binding.activation_mode ?? "always") === "always")
                        }
                        onChange={(event) =>
                          setDraft((current) =>
                            activateBinding(
                              current,
                              binding.skill_id,
                              event.target.value === "on_demand" ? "on_demand" : "always"
                            )
                          )
                        }
                      >
                        <option value="always">{t("skills_activation_mode_always")}</option>
                        <option value="on_demand" disabled={!canChooseOnDemand}>
                          {t("skills_activation_mode_on_demand")}
                        </option>
                      </select>
                    </label>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-1 sm:justify-end">
                  {attachableId &&
                    attachableId !== binding.skill_revision_id &&
                    active &&
                    !blocked &&
                    summary && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!canEdit || upgradeBusy !== null}
                        onClick={() => void upgradeToLatest(summary, attachableId)}
                      >
                        <RefreshCw className="size-4" />
                        {t("skills_use_latest_revision")}
                      </Button>
                    )}
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("skills_move_up_aria", { name })}
                    disabled={!canEdit || index === 0}
                    onClick={() => setDraft((current) => moveBinding(current, index, -1))}
                  >
                    <ArrowUp className="size-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("skills_move_down_aria", { name })}
                    disabled={!canEdit || index === draft.length - 1}
                    onClick={() => setDraft((current) => moveBinding(current, index, 1))}
                  >
                    <ArrowDown className="size-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("skills_remove_aria", { name })}
                    disabled={!canEdit}
                    onClick={() => setDraft((current) => removeBinding(current, binding.skill_id))}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setShowPicker((value) => !value)}>
            <Plus className="size-4" />
            {t("skills_add_existing")}
          </Button>
          {canCreate && (
            <Button variant="outline" onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" />
              {t("skills_create_new")}
            </Button>
          )}
        </div>
      )}
      {showPicker && (
        <div className="space-y-3 rounded-lg border p-4">
          <Input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder={t("skills_search_existing")}
            aria-label={t("skills_search_existing")}
          />
          {catalogue.isPending ? (
            <p role="status">{t("loading")}</p>
          ) : catalogue.isError && !catalogue.data ? (
            <Button variant="outline" onClick={() => void catalogue.refetch()}>
              {t("retry")}
            </Button>
          ) : choices.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {t(search ? "skills_search_no_results" : "skills_no_available")}
            </p>
          ) : (
            <ul className="max-h-72 divide-y overflow-y-auto">
              {choices.map((skill) => (
                <li key={skill.id}>
                  <button
                    type="button"
                    className="hover:bg-muted w-full rounded-md p-3 text-left"
                    onClick={() => void openPreview(skill)}
                  >
                    <span className="font-medium">{skill.display_name}</span>
                    <span className="text-muted-foreground ml-2 text-xs">
                      {t("skills_revision_label", {
                        revision: String(candidateRevisionNumber(skill))
                      })}
                    </span>
                    <p className="text-muted-foreground text-sm">{skill.description}</p>
                    <span className="text-muted-foreground text-xs">
                      {t(
                        skill.source === "organization"
                          ? "skills_source_organization"
                          : "skills_source_space"
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {catalogue.hasNextPage && (
            <Button
              variant="ghost"
              disabled={catalogue.isFetchingNextPage}
              onClick={() => void catalogue.fetchNextPage()}
            >
              {catalogue.isFetchingNextPage ? t("loading") : t("load_more")}
            </Button>
          )}
        </div>
      )}
      {resource !== "personal_chat" && (
        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <Button
            disabled={!canEdit}
            aria-busy={saving || undefined}
            onClick={() => void saveDraft()}
          >
            {saving ? t("saving") : t("skills_bindings_save")}
          </Button>
          <Button variant="ghost" disabled={saving} onClick={discardDraft}>
            {t("discard_changes")}
          </Button>
          {dirty && (
            <span className="text-muted-foreground text-sm">{t("skills_form_unsaved_status")}</span>
          )}
        </div>
      )}
      {resource !== "personal_chat" && saveError && (
        <p role="alert" className="text-destructive text-sm">
          {saveError}
        </p>
      )}
      <p role="status" className={announcement ? "text-sm" : "sr-only"}>
        {announcement}
      </p>
      <Dialog
        open={previewCandidate !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPreviewCandidate(null);
            setPreview(null);
          }
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {t("skills_preview_title", {
                name: preview?.displayName ?? previewCandidate?.display_name ?? t("skills")
              })}
            </DialogTitle>
            <DialogDescription>{t("skills_preview_description")}</DialogDescription>
          </DialogHeader>
          {previewLoading ? (
            <p>{t("loading")}</p>
          ) : previewError ? (
            <p role="alert" className="text-destructive">
              {previewError}
            </p>
          ) : (
            preview && (
              <div className="space-y-3">
                <p>{preview.description}</p>
                <Badge variant="outline">
                  {t("skills_revision_label", { revision: String(preview.revisionNumber) })}
                </Badge>
                <pre className="bg-muted/40 max-h-[50dvh] overflow-y-auto rounded-lg border p-4 font-mono text-sm whitespace-pre-wrap">
                  {preview.instructions}
                </pre>
              </div>
            )
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPreviewCandidate(null)}>
              {t("cancel")}
            </Button>
            <Button disabled={!preview} onClick={attachPreview}>
              {t("skills_add_to_draft")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          if (!open && createDirty && !window.confirm(t("unsaved_changes_warning"))) return;
          setCreateOpen(open);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t("skills_create_dialog_title")}</DialogTitle>
            <DialogDescription>{t("skills_create_dialog_description")}</DialogDescription>
          </DialogHeader>
          <Alert>
            <AlertTitle>{t("skills_create_immediate_title")}</AlertTitle>
            <AlertDescription>{t("skills_create_immediate_description")}</AlertDescription>
          </Alert>
          <SkillForm mode="create" onDirtyChange={setCreateDirty} onSubmit={createSkill} />
        </DialogContent>
      </Dialog>
    </SettingsGroup>
  );
}
