"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cloud, Globe, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatBytes } from "@/lib/format";
import { useJobs } from "@/features/jobs/use-jobs";
import { useSpace } from "@/features/spaces/use-space";
import { EmbeddingModelSelect } from "../../embedding-model-select";
import {
  integrationPreviewQueryOptions,
  type IntegrationPreview,
  type UserIntegration
} from "../queries";
import { SharePointFolderTree } from "./folder-tree";
import { ImportPreviewError } from "./preview-state";
import {
  buildBatchItems,
  buildSelectionKey,
  dedupeNestedSelection,
  type SelectedImportItem,
  type SelectedTreeItem
} from "./selection";

type PreviewCategory =
  "my_teams" | "public_teams_not_member" | "other_sites" | "onedrive" | "unknown";

const CATEGORY_ORDER: PreviewCategory[] = [
  "my_teams",
  "public_teams_not_member",
  "other_sites",
  "onedrive",
  "unknown"
];

function previewCategory(site: IntegrationPreview): PreviewCategory {
  if (site.type === "onedrive") return "onedrive";
  const category = site.category as PreviewCategory | null | undefined;
  return category && CATEGORY_ORDER.includes(category) ? category : "other_sites";
}

function categoryLabel(category: PreviewCategory, t: (key: string) => string): string {
  switch (category) {
    case "my_teams":
      return t("sharepoint_category_my_teams");
    case "public_teams_not_member":
      return t("sharepoint_category_public_teams_not_member");
    case "other_sites":
      return t("sharepoint_category_other_sites");
    case "onedrive":
      return "OneDrive";
    case "unknown":
      return t("sharepoint_category_unknown");
  }
}

/**
 * SharePoint import: pick a site (grouped by category), browse its tree,
 * select files/folders (nested picks deduped), name the wrapper when more
 * than one item is imported, then batch-import.
 */
export function SharePointImportDialog({
  open,
  onOpenChange,
  onBack,
  integration
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onBack: () => void;
  integration: UserIntegration;
}) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const { trackJob } = useJobs();

  const [search, setSearch] = useState("");
  const [showPublicTeams, setShowPublicTeams] = useState(true);
  const [site, setSite] = useState<IntegrationPreview | null>(null);
  const [selected, setSelected] = useState<SelectedImportItem[]>([]);
  const [wrapperName, setWrapperName] = useState("");
  const [embeddingModelId, setEmbeddingModelId] = useState<string | undefined>(
    space.embedding_models[0]?.id
  );

  const userIntegrationId = integration.id ?? "";
  const preview = useQuery({
    ...integrationPreviewQueryOptions(browserApi, userIntegrationId),
    enabled: open && userIntegrationId.length > 0
  });

  const groups = useMemo(() => {
    const sites = preview.data ?? [];
    const query = search.toLowerCase();
    const filtered = sites
      .filter((entry) => entry.name.toLowerCase().includes(query))
      .filter((entry) => showPublicTeams || previewCategory(entry) !== "public_teams_not_member");
    return CATEGORY_ORDER.map((category) => ({
      category,
      items: filtered
        .filter((entry) => previewCategory(entry) === category)
        .sort((a, b) => a.name.localeCompare(b.name))
    })).filter((group) => group.items.length > 0);
  }, [preview.data, search, showPublicTeams]);

  const hasPublicTeams = (preview.data ?? []).some(
    (entry) => previewCategory(entry) === "public_teams_not_member"
  );
  const settingsHref = space.personal ? "/account/integrations" : null;

  const deduped = dedupeNestedSelection(selected);
  const requiresWrapperName = deduped.effectiveEntries.length > 1;
  const wrapperNameMissing = requiresWrapperName && wrapperName.trim().length === 0;

  function reset() {
    setSite(null);
    setSelected([]);
    setWrapperName("");
    setSearch("");
  }

  function toggleSelect(item: SelectedTreeItem) {
    const key = buildSelectionKey(item);
    setSelected((current) =>
      current.some((entry) => entry.selectionKey === key)
        ? current.filter((entry) => entry.selectionKey !== key)
        : [...current, { selectionKey: key, item, importName: item.name }]
    );
  }

  function updateImportName(key: string, name: string) {
    setSelected((current) =>
      current.map((entry) => (entry.selectionKey === key ? { ...entry, importName: name } : entry))
    );
  }

  const importBatch = useMutation({
    mutationFn: () => {
      if (!site || !embeddingModelId) throw new Error("unreachable: gated by disabled state");
      return unwrap(
        browserApi.POST(
          "/api/v1/spaces/{id}/knowledge/integrations/add/{user_integration_id}/batch/",
          {
            params: { path: { id: space.id, user_integration_id: userIntegrationId } },
            body: {
              embedding_model: { id: embeddingModelId },
              wrapper_name: requiresWrapperName ? wrapperName.trim() : undefined,
              items: buildBatchItems(
                { key: site.key, name: site.name, url: site.url, type: site.type },
                deduped.effectiveEntries
              )
            }
          }
        )
      );
    },
    onSuccess: (result) => {
      trackJob();
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      if (result.created_count === 0) {
        toast.error(
          t("sharepoint_batch_import_all_failed", { failed: String(result.failed_count) })
        );
        return;
      }
      reset();
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const selectedKeys = new Set(selected.map((entry) => entry.selectionKey));

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("import_knowledge_from_sharepoint")}</DialogTitle>
        </DialogHeader>

        {space.embedding_models.length === 0 && (
          <p className="border-warning/30 bg-warning/10 text-warning rounded-md border px-3 py-2 text-sm">
            <span className="font-semibold">{t("warning")}:</span>{" "}
            {t("warning_no_embedding_models")}
          </p>
        )}

        {!site ? (
          <div className="flex flex-col gap-2">
            <Label htmlFor="sharepoint-site-search">{t("import_knowledge_from")}</Label>
            <div className="relative">
              <Input
                id="sharepoint-site-search"
                value={search}
                placeholder={t("find_sharepoint_site")}
                onChange={(event) => setSearch(event.target.value)}
              />
              <Search className="text-muted-foreground absolute top-1/2 right-3 size-4 -translate-y-1/2" />
            </div>
            {hasPublicTeams && (
              <label className="text-muted-foreground flex items-center gap-2 px-1 text-sm">
                <Checkbox
                  checked={showPublicTeams}
                  onCheckedChange={(checked) => setShowPublicTeams(checked === true)}
                />
                {t("sharepoint_toggle_public_non_member_teams")}
              </label>
            )}
            <div className="max-h-[40vh] overflow-y-auto rounded-md border p-1">
              {userIntegrationId.length === 0 ? (
                <ImportPreviewError
                  message={t("integration_preview_connection_missing")}
                  onBack={onBack}
                  settingsHref={settingsHref}
                />
              ) : preview.isError ? (
                <ImportPreviewError
                  message={t("integration_preview_failed")}
                  onBack={onBack}
                  onRetry={() => void preview.refetch()}
                  settingsHref={settingsHref}
                />
              ) : preview.isPending ? (
                <div className="text-muted-foreground flex items-center gap-2 px-2 py-3 text-sm">
                  <Spinner /> {t("loading_available_sites")}
                </div>
              ) : groups.length === 0 ? (
                <p className="text-muted-foreground px-2 py-3 text-sm">
                  {t("no_matching_sites_found")}
                </p>
              ) : (
                groups.map((group) => (
                  <div key={group.category}>
                    <div className="text-muted-foreground px-2 pt-2 pb-1 text-xs font-medium tracking-wide uppercase">
                      {categoryLabel(group.category, t)}
                    </div>
                    {group.items.map((entry) => (
                      <button
                        key={entry.key}
                        type="button"
                        className="hover:bg-muted/50 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left"
                        onClick={() => {
                          setSite(entry);
                          setSelected([]);
                          setWrapperName("");
                        }}
                      >
                        {entry.type === "onedrive" ? (
                          <Cloud className="text-muted-foreground size-4 shrink-0" />
                        ) : (
                          <Globe className="text-muted-foreground size-4 shrink-0" />
                        )}
                        <span className="truncate text-sm">{entry.name}</span>
                      </button>
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>
        ) : (
          <div className="flex max-h-[56vh] min-h-0 flex-col gap-3 overflow-y-auto pr-1">
            <SharePointFolderTree
              userIntegrationId={userIntegrationId}
              spaceId={space.id}
              site={{ key: site.key, name: site.name, type: site.type }}
              selectedKeys={selectedKeys}
              onToggleSelect={toggleSelect}
            />

            {selected.length > 0 && (
              <>
                <div className="bg-accent rounded-md border px-3 py-2">
                  <div className="text-sm font-medium">
                    {t("sharepoint_selected_items_count", { count: String(selected.length) })}
                  </div>
                  {deduped.excludedKeys.size > 0 && (
                    <div className="text-muted-foreground mt-1 text-xs">
                      {t("sharepoint_nested_selection_notice", {
                        count: String(deduped.excludedKeys.size)
                      })}
                    </div>
                  )}
                </div>

                {requiresWrapperName && (
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="sharepoint-wrapper-name">
                      {t("sharepoint_wrapper_name_label")}{" "}
                      <span className="text-destructive">*</span>
                    </Label>
                    <p className="text-muted-foreground text-xs">
                      {t("sharepoint_wrapper_name_required_hint")}
                    </p>
                    <Input
                      id="sharepoint-wrapper-name"
                      value={wrapperName}
                      placeholder={t("sharepoint_wrapper_name_placeholder")}
                      aria-invalid={wrapperNameMissing}
                      onChange={(event) => setWrapperName(event.target.value)}
                    />
                    {wrapperNameMissing && (
                      <p className="text-destructive text-xs">
                        {t("sharepoint_wrapper_name_missing_hint")}
                      </p>
                    )}
                  </div>
                )}

                <div className="max-h-48 overflow-y-auto rounded-md border">
                  {selected.map((entry) => (
                    <div key={entry.selectionKey} className="border-b px-3 py-2 last:border-b-0">
                      <div className="flex items-center gap-2">
                        <Input
                          className="h-8 min-w-0 flex-1 text-sm"
                          value={entry.importName}
                          onChange={(event) =>
                            updateImportName(entry.selectionKey, event.target.value)
                          }
                        />
                        <Button variant="ghost" size="sm" onClick={() => toggleSelect(entry.item)}>
                          {t("remove")}
                        </Button>
                      </div>
                      <div className="text-muted-foreground mt-1 flex min-w-0 items-center gap-2 text-xs">
                        <span className="min-w-0 flex-1 truncate">{entry.item.path}</span>
                        {entry.item.size != null && (
                          <span className="shrink-0">({formatBytes(entry.item.size)})</span>
                        )}
                        {deduped.excludedKeys.has(entry.selectionKey) && (
                          <span className="shrink-0">
                            {t("sharepoint_nested_selection_skipped")}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        <EmbeddingModelSelect
          models={space.embedding_models}
          value={embeddingModelId}
          onChange={setEmbeddingModelId}
        />

        <DialogFooter>
          {wrapperNameMissing && (
            <span className="text-muted-foreground mr-auto self-center text-xs">
              {t("sharepoint_wrapper_name_missing_hint")}
            </span>
          )}
          <Button
            variant="outline"
            onClick={() => {
              if (site) {
                setSite(null);
                setSelected([]);
                setWrapperName("");
              } else {
                onBack();
              }
            }}
          >
            {t("back")}
          </Button>
          <Button
            disabled={
              importBatch.isPending ||
              space.embedding_models.length === 0 ||
              !embeddingModelId ||
              !site ||
              deduped.effectiveEntries.length === 0 ||
              wrapperNameMissing
            }
            onClick={() => importBatch.mutate()}
          >
            {importBatch.isPending ? t("importing") : t("import")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
