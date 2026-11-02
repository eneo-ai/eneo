import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  Cloud,
  File,
  FileAudio,
  FileImage,
  FileText,
  Folder,
  Globe,
  Search
} from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { useEffect, useId, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { LoadingState } from "@/components/composites/loading-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { formatSourceMetadataValue } from "../../source-metadata";
import {
  sharepointSearchQueryOptions,
  sharepointTreeQueryOptions,
  type SharePointTreeItem
} from "../queries";
import { buildSelectionKey, isDescendantPath, type SelectedTreeItem } from "./selection";
import {
  SharePointFilters,
  SharePointFilterChips,
  type SharePointFacets
} from "./sharepoint-filters";

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "svg", "bmp", "webp", "ico", "tiff"];
const AUDIO_EXTENSIONS = ["mp3", "wav", "ogg", "flac", "aac", "wma", "m4a"];
const TEXT_EXTENSIONS = "doc docx pdf txt rtf odt xls xlsx csv ppt pptx md html xml json".split(
  " "
);

function FileIcon({ name }: { name: string }) {
  const parts = name.split(".");
  const extension = parts.length > 1 ? (parts.at(-1)?.toLowerCase() ?? "") : "";
  const className = "text-muted-foreground size-4 shrink-0";
  if (IMAGE_EXTENSIONS.includes(extension)) return <FileImage className={className} />;
  if (AUDIO_EXTENSIONS.includes(extension)) return <FileAudio className={className} />;
  if (TEXT_EXTENSIONS.includes(extension)) return <FileText className={className} />;
  return <File className={className} />;
}

function toSelectable(item: SharePointTreeItem): SelectedTreeItem | null {
  if (item.type !== "file" && item.type !== "folder" && item.type !== "site_root") return null;
  return {
    id: item.id,
    name: item.name,
    type: item.type,
    path: item.path,
    web_url: item.web_url,
    size: item.size
  };
}

type Crumb = { folderId: string | null; path: string; name: string };

/** Folder browsing stays local; search and property filters cover the whole library. */
export function SharePointFolderTree({
  userIntegrationId,
  spaceId,
  site,
  selectedKeys,
  selectedPaths,
  onToggleSelect,
  onSelectMany,
  onDeselectMany
}: {
  userIntegrationId: string;
  spaceId: string;
  site: { key: string; name: string; type: string };
  selectedKeys: ReadonlySet<string>;
  selectedPaths: readonly string[];
  onToggleSelect: (item: SelectedTreeItem) => void;
  onSelectMany: (items: SelectedTreeItem[]) => void;
  onDeselectMany: (items: SelectedTreeItem[]) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const announce = useAnnounce();
  const searchHelpId = useId();
  const isOneDrive = site.type === "onedrive";
  const [stack, setStack] = useState<Crumb[]>([{ folderId: null, path: "/", name: site.name }]);
  const [search, setSearch] = useState("");
  const [facets, setFacets] = useState<SharePointFacets>({});
  const q = search.trim();
  const debouncedQ = useDebouncedValue(q);
  const filters = Object.entries(facets)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, value]) => `${name}:${value}`);
  const searching = q.length > 0 || filters.length > 0;
  const debouncing = q !== debouncedQ;
  const current = stack.at(-1)!;
  const scope = {
    userIntegrationId,
    spaceId,
    siteId: isOneDrive ? undefined : site.key,
    driveId: isOneDrive ? site.key : undefined
  };
  // Root metadata owns the available columns, even while a child folder is open.
  const root = useQuery(sharepointTreeQueryOptions(browserApi, scope));
  const tree = useQuery(
    sharepointTreeQueryOptions(browserApi, {
      ...scope,
      folderId: current.folderId ?? undefined,
      folderPath: current.path === "/" ? undefined : current.path
    })
  );
  const results = useQuery({
    ...sharepointSearchQueryOptions(browserApi, { ...scope, q, filters }),
    enabled: searching && !debouncing
  });
  const listing = searching ? results : tree;
  const columns = root.data?.columns ?? [];
  const covered = (item: SelectedTreeItem) =>
    selectedPaths.some((path) => isDescendantPath(item.path, path));
  const editableMatches =
    searching && !debouncing
      ? (results.data?.items ?? []).flatMap((item) => {
          const candidate = toSelectable(item);
          return candidate && !covered(candidate) ? [candidate] : [];
        })
      : [];
  const allMatchesSelected =
    editableMatches.length > 0 &&
    editableMatches.every((item) => selectedKeys.has(buildSelectionKey(item)));
  const resultCount = results.data?.items.length ?? 0;
  const countText = t(
    resultCount === 1 ? "sharepoint_search_results_one" : "sharepoint_search_results_other",
    { count: String(resultCount) }
  );
  const notice = listing.data?.truncated
    ? searching
      ? t("sharepoint_search_truncated", { count: String(resultCount) })
      : t("sharepoint_tree_truncated")
    : "";
  useEffect(() => {
    if (listing.data && !listing.isFetching && !debouncing) {
      const message = [searching ? countText : "", notice].filter(Boolean).join(" ");
      if (message) announce(message);
    }
  }, [announce, countText, debouncing, listing.data, listing.isFetching, notice, searching]);
  const siteRootItem: SelectedTreeItem = { id: "", name: site.name, type: "site_root", path: "/" };

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <p className="text-ax-text-secondary text-sm">{t("sharepoint_tree_selection_description")}</p>
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <TextInput
            label={t("sharepoint_search_content", { name: site.name })}
            isLabelHidden
            role="searchbox"
            value={search}
            onChange={(value) => setSearch(value.slice(0, 200))}
            startIcon={Search}
            hasClear
            width="100%"
            placeholder={t("sharepoint_search_content", { name: site.name })}
            aria-describedby={searchHelpId}
          />
        </div>
        <SharePointFilters columns={columns} facets={facets} onChange={setFacets} />
      </div>
      <p id={searchHelpId} className="text-ax-text-secondary text-xs">
        {t("sharepoint_search_help")}
      </p>
      <SharePointFilterChips columns={columns} facets={facets} onChange={setFacets} />
      {searching && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            label={t("sharepoint_search_clear")}
            onClick={() => {
              setSearch("");
              setFacets({});
            }}
          />
          {editableMatches.length > 0 && (
            <Button
              size="sm"
              variant="secondary"
              label={
                allMatchesSelected
                  ? t("sharepoint_deselect_all_matches")
                  : t("sharepoint_select_all_matches", { count: String(editableMatches.length) })
              }
              onClick={() =>
                allMatchesSelected ? onDeselectMany(editableMatches) : onSelectMany(editableMatches)
              }
            />
          )}
        </div>
      )}

      {!searching && stack.length > 1 && (
        <nav aria-label={site.name} className="flex flex-wrap items-center gap-1 text-sm">
          {stack.map((crumb, index) => (
            <span key={crumb.folderId ?? "root"} className="flex min-w-0 items-center gap-1">
              {index > 0 && <ChevronRight aria-hidden className="size-3 shrink-0" />}
              {index < stack.length - 1 ? (
                <button
                  type="button"
                  className="text-ax-text-secondary focus-visible:outline-ring min-h-6 rounded px-1 text-left break-words hover:underline focus-visible:outline-2 pointer-coarse:min-h-11"
                  onClick={() => setStack(stack.slice(0, index + 1))}
                >
                  {crumb.name}
                </button>
              ) : (
                <span aria-current="location" className="font-medium break-words">
                  {crumb.name}
                </span>
              )}
            </span>
          ))}
        </nav>
      )}
      <div className="max-h-[42dvh] min-h-0 overflow-x-hidden overflow-y-auto rounded-md border">
        {searching && debouncing ? (
          <LoadingState rows={3} label={t("sharepoint_searching")} />
        ) : (
          <QueryStateBoundary<{ items: SharePointTreeItem[]; truncated?: boolean }>
            query={listing}
            rows={3}
            loadingLabel={t(searching ? "sharepoint_searching" : "sharepoint_loading_content")}
            errorTitle={t(searching ? "sharepoint_search_error" : "sharepoint_tree_load_error")}
          >
            {(data) => (
              <>
                {searching && (
                  <p className="text-ax-text-secondary px-3 py-2 text-xs">
                    {t(
                      data.items.length === 1
                        ? "sharepoint_search_results_one"
                        : "sharepoint_search_results_other",
                      { count: String(data.items.length) }
                    )}
                  </p>
                )}
                {!searching && stack.length === 1 && (
                  <div className="border-b px-3 py-2">
                    <CheckboxInput
                      label={t(isOneDrive ? "import_entire_onedrive" : "import_entire_site")}
                      labelIcon={isOneDrive ? Cloud : Globe}
                      value={
                        selectedKeys.has(buildSelectionKey(siteRootItem))
                          ? true
                          : selectedKeys.size > 0
                            ? "indeterminate"
                            : false
                      }
                      onChange={() => onToggleSelect(siteRootItem)}
                    />
                  </div>
                )}
                {data.items.length === 0 && (
                  <p className="text-ax-text-secondary px-3 py-4 text-sm">
                    {t(searching ? "sharepoint_search_no_results" : "no_items")}
                  </p>
                )}
                <ul aria-label={searching ? t("sharepoint_search_results_label") : site.name}>
                  {data.items.map((item) => {
                    const selectable = toSelectable(item);
                    if (!selectable) return null;
                    const key = buildSelectionKey(selectable);
                    const byParent = covered(selectable);
                    return (
                      <li
                        key={key}
                        className="flex min-w-0 items-start gap-2 border-b px-3 py-2 last:border-b-0"
                      >
                        {!searching &&
                          (item.type === "folder" ? (
                            <button
                              type="button"
                              className="text-ax-text-secondary focus-visible:outline-ring flex size-6 shrink-0 items-center justify-center rounded focus-visible:outline-2 pointer-coarse:size-11"
                              aria-label={t("open_folder")}
                              onClick={() =>
                                setStack([
                                  ...stack,
                                  { folderId: item.id, path: item.path, name: item.name }
                                ])
                              }
                            >
                              <ChevronRight aria-hidden className="size-4" />
                            </button>
                          ) : (
                            <span aria-hidden className="size-6 shrink-0 pointer-coarse:size-11" />
                          ))}
                        <div className="min-w-0 flex-1 break-words">
                          <CheckboxInput
                            label={item.name}
                            labelIcon={
                              item.type === "folder" ? (
                                <Folder aria-hidden />
                              ) : (
                                <FileIcon name={item.name} />
                              )
                            }
                            value={selectedKeys.has(key) || byParent}
                            isDisabled={byParent}
                            disabledMessage={
                              byParent ? t("sharepoint_selected_by_parent") : undefined
                            }
                            onChange={() => onToggleSelect(selectable)}
                            description={searching ? item.path : undefined}
                          />
                          {searching &&
                            (item.source_metadata ?? []).map((entry) => (
                              <p
                                key={entry.name}
                                className="text-ax-text-secondary mt-1 text-xs break-words"
                              >
                                {entry.label}:{" "}
                                {formatSourceMetadataValue(entry, {
                                  locale,
                                  yes: t("yes"),
                                  no: t("no")
                                })}
                              </p>
                            ))}
                        </div>
                        {item.type === "file" && item.size != null && (
                          <span className="text-ax-text-secondary shrink-0 text-xs tabular-nums">
                            {formatBytes(item.size, locale)}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
                {data.truncated && (
                  <p className="text-ax-text-secondary px-3 py-3 text-xs">
                    {searching
                      ? t("sharepoint_search_truncated", { count: String(data.items.length) })
                      : t("sharepoint_tree_truncated")}
                  </p>
                )}
              </>
            )}
          </QueryStateBoundary>
        )}
      </div>
    </div>
  );
}
