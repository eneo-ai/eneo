"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  Cloud,
  File,
  FileAudio,
  FileImage,
  FileText,
  Folder,
  Globe
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Spinner } from "@/components/ui/spinner";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
import { sharepointTreeQueryOptions, type SharePointTreeItem } from "../queries";
import { buildSelectionKey, type SelectedTreeItem } from "./selection";

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "svg", "bmp", "webp", "ico", "tiff"];
const AUDIO_EXTENSIONS = ["mp3", "wav", "ogg", "flac", "aac", "wma", "m4a"];
const TEXT_EXTENSIONS = "doc docx pdf txt rtf odt xls xlsx csv ppt pptx md html xml json".split(
  " "
);

const SITE_ROOT_KEY = buildSelectionKey({ id: "", type: "site_root", path: "/" });

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

/**
 * One-level-at-a-time SharePoint browser with breadcrumb navigation and an
 * "import entire site" row at the root. Ported from SharePointFolderTree.svelte.
 */
export function SharePointFolderTree({
  userIntegrationId,
  spaceId,
  site,
  selectedKeys,
  onToggleSelect
}: {
  userIntegrationId: string;
  spaceId: string;
  site: { key: string; name: string; type: string };
  selectedKeys: ReadonlySet<string>;
  onToggleSelect: (item: SelectedTreeItem) => void;
}) {
  const t = useTranslations();
  const isOneDrive = site.type === "onedrive";
  const [stack, setStack] = useState<Crumb[]>([{ folderId: null, path: "/", name: site.name }]);
  const current = stack.at(-1) ?? { folderId: null, path: "/", name: site.name };

  const { data, isPending } = useQuery(
    sharepointTreeQueryOptions(browserApi, {
      userIntegrationId,
      spaceId,
      siteId: isOneDrive ? undefined : site.key,
      driveId: isOneDrive ? site.key : undefined,
      folderId: current.folderId ?? undefined,
      folderPath: current.path === "/" ? undefined : current.path
    })
  );
  const items = data?.items ?? [];

  function navigateInto(item: SharePointTreeItem) {
    setStack((crumbs) => [...crumbs, { folderId: item.id, path: item.path, name: item.name }]);
  }

  function navigateTo(index: number) {
    setStack((crumbs) => (index < crumbs.length - 1 ? crumbs.slice(0, index + 1) : crumbs));
  }

  const siteRootItem: SelectedTreeItem = {
    id: "",
    name: site.name,
    type: "site_root",
    path: "/"
  };

  return (
    <div className="flex min-h-0 flex-col gap-2">
      {stack.length > 1 && (
        <nav className="flex min-h-7 flex-wrap items-center gap-0.5 text-sm">
          {stack.map((crumb, index) => (
            <span
              key={`${crumb.folderId ?? "root"}-${index}`}
              className="flex items-center gap-0.5"
            >
              {index > 0 && <ChevronRight className="text-muted-foreground size-3 shrink-0" />}
              {index < stack.length - 1 ? (
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground max-w-[150px] truncate rounded px-1 py-0.5 hover:underline"
                  onClick={() => navigateTo(index)}
                >
                  {crumb.name}
                </button>
              ) : (
                <span className="max-w-[200px] truncate px-1 py-0.5 font-medium">{crumb.name}</span>
              )}
            </span>
          ))}
        </nav>
      )}

      <div className="max-h-[42vh] min-h-0 overflow-x-hidden overflow-y-auto rounded-md border">
        {isPending ? (
          <div className="text-muted-foreground flex items-center gap-2 px-4 py-8">
            <Spinner /> {t("loading_available_sites")}
          </div>
        ) : items.length === 0 && stack.length > 1 ? (
          <div className="text-muted-foreground px-4 py-4 text-sm">{t("no_items")}</div>
        ) : (
          <div className="flex flex-col">
            {stack.length <= 1 && (
              <div
                className={`flex w-full items-center gap-2 border-b px-3 py-1.5 transition-colors ${
                  selectedKeys.has(SITE_ROOT_KEY) ? "bg-accent" : "hover:bg-muted/50"
                }`}
              >
                <div className="w-3.5" />
                <Checkbox
                  checked={selectedKeys.has(SITE_ROOT_KEY)}
                  onCheckedChange={() => onToggleSelect(siteRootItem)}
                  aria-label={isOneDrive ? t("import_entire_onedrive") : t("import_entire_site")}
                />
                {isOneDrive ? (
                  <Cloud className="text-muted-foreground size-4 shrink-0" />
                ) : (
                  <Globe className="text-muted-foreground size-4 shrink-0" />
                )}
                <button
                  type="button"
                  className="w-full min-w-0 truncate text-left text-sm font-medium"
                  onClick={() => onToggleSelect(siteRootItem)}
                >
                  {isOneDrive ? t("import_entire_onedrive") : t("import_entire_site")}
                </button>
              </div>
            )}
            {items.map((item) => {
              const selectable = toSelectable(item);
              if (!selectable) return null;
              const key = buildSelectionKey(selectable);
              return (
                <div
                  key={key}
                  className={`flex w-full min-w-0 items-center gap-2 border-b px-3 py-1.5 transition-colors last:border-b-0 ${
                    selectedKeys.has(key) ? "bg-accent" : "hover:bg-muted/50"
                  }`}
                >
                  {item.type === "folder" ? (
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground size-3.5 shrink-0"
                      onClick={() => navigateInto(item)}
                      title={t("open_folder")}
                      aria-label={t("open_folder")}
                    >
                      <ChevronRight className="size-3.5" />
                    </button>
                  ) : (
                    <div className="size-3.5" />
                  )}
                  <Checkbox
                    checked={selectedKeys.has(key)}
                    onCheckedChange={() => onToggleSelect(selectable)}
                    aria-label={item.name}
                  />
                  <button
                    type="button"
                    className="flex w-full min-w-0 items-center gap-2 text-left"
                    onClick={() => onToggleSelect(selectable)}
                  >
                    {item.type === "folder" ? (
                      <Folder className="text-muted-foreground size-4 shrink-0" />
                    ) : (
                      <FileIcon name={item.name} />
                    )}
                    <span className="flex-1 truncate text-sm" title={item.name}>
                      {item.name}
                    </span>
                    {item.type !== "folder" && item.size != null && (
                      <span className="text-muted-foreground hidden shrink-0 text-xs tabular-nums md:inline">
                        {formatBytes(item.size)}
                      </span>
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
