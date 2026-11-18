import { IconButton } from "@astryxdesign/core/IconButton";
import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Folder } from "lucide-react";
import { useId, useState } from "react";
import { useFormatter, useTranslations } from "use-intl";
import { inPlaceLink, type InPlaceLink } from "@/components/composites/in-place-link";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import Link from "@/lib/link";
import { cn } from "@/lib/utils";
import { websiteFoldersQueryOptions, type WebsiteContentFolder } from "./knowledge";

type NavigationProps = {
  websiteId: string;
  selectedPrefix: string;
  linkFor: (prefix: string) => InPlaceLink;
};

const LINK =
  "focus-visible:outline-ring rounded-ax-inner flex min-h-9 min-w-0 flex-1 items-center gap-2 px-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11";

function FolderLink({
  prefix,
  label,
  count,
  selectedPrefix,
  linkFor
}: Pick<NavigationProps, "selectedPrefix" | "linkFor"> & {
  prefix: string;
  label: string;
  count: number;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const selected = prefix === selectedPrefix;
  return (
    <Link
      {...linkFor(prefix)}
      prefetch={false}
      aria-current={selected ? "page" : undefined}
      className={cn(LINK, selected ? "bg-ax-selected font-medium" : "hover:bg-ax-hover")}
    >
      <Folder aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
      <span className="min-w-0 flex-1 break-all">{label}</span>
      <span className="sr-only">
        {t(
          count === 1 ? "website_source_resource_count_one" : "website_source_resource_count_other",
          { count }
        )}
      </span>
      <span aria-hidden="true" className="text-ax-text-secondary text-xs tabular-nums">
        {format.number(count)}
      </span>
    </Link>
  );
}

function FolderRow({
  item,
  parent,
  autoExpand,
  ...navigation
}: NavigationProps & { item: WebsiteContentFolder; parent: string; autoExpand: boolean }) {
  const t = useTranslations();
  const { selectedPrefix } = navigation;
  const ancestor = selectedPrefix !== item.path && selectedPrefix.startsWith(item.path);
  const [expansion, setExpansion] = useState({
    selection: selectedPrefix,
    open: autoExpand || ancestor
  });
  if (expansion.selection !== selectedPrefix) {
    setExpansion({ selection: selectedPrefix, open: expansion.open || ancestor });
  }
  const expanded = expansion.open;
  const branchId = useId();
  const raw = parent
    ? item.path.slice(parent.length, -1)
    : item.path.replace(/^https?:\/\//, "").replace(/\/$/, "");
  let label = raw;
  try {
    label = decodeURIComponent(raw);
  } catch {
    /* A literal percent in a URL is still readable. */
  }
  return (
    <li>
      <div className="flex items-center">
        {item.has_children ? (
          <IconButton
            label={t(expanded ? "source_tree_collapse" : "source_tree_expand", { name: label })}
            icon={
              expanded ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />
            }
            variant="ghost"
            aria-expanded={expanded}
            aria-controls={expanded ? branchId : undefined}
            onClick={() => setExpansion({ selection: selectedPrefix, open: !expanded })}
          />
        ) : (
          <span className="w-9 shrink-0 pointer-coarse:w-11" aria-hidden="true" />
        )}
        <FolderLink {...navigation} prefix={item.path} label={label} count={item.count} />
      </div>
      {item.has_children && expanded && (
        <div id={branchId} className="ps-3">
          <FolderBranch {...navigation} prefix={item.path} />
        </div>
      )}
    </li>
  );
}

function FolderBranch({ prefix, ...navigation }: NavigationProps & { prefix: string }) {
  const t = useTranslations();
  const query = useInfiniteQuery(
    websiteFoldersQueryOptions(browserApi, navigation.websiteId, prefix)
  );
  // Navigation uses ordinary links and disclosure buttons, as integration folders do.
  // TreeList's internal expansion cannot own these independently paged server branches.
  return (
    <QueryStateBoundary query={query} rows={2} errorTitle={t("source_tree_retry")}>
      {(data) => {
        const items = [
          ...new Map(
            data.pages.flatMap((page) => page.items).map((item) => [item.path, item])
          ).values()
        ];
        return (
          <>
            <ul className="flex flex-col gap-1">
              {items.map((item) => (
                <FolderRow
                  key={item.path}
                  item={item}
                  parent={prefix}
                  autoExpand={!prefix && items.length === 1}
                  {...navigation}
                />
              ))}
            </ul>
            <LoadMore query={query} label={t("source_tree_more")} />
          </>
        );
      }}
    </QueryStateBoundary>
  );
}

export function WebsiteFolderNav({
  websiteId,
  selectedPrefix,
  total,
  hrefFor,
  onSelect
}: {
  websiteId: string;
  selectedPrefix: string;
  total: number;
  hrefFor: (prefix: string) => string;
  onSelect: (prefix: string) => void;
}) {
  const t = useTranslations();
  const headingId = useId();
  const navigation = {
    websiteId,
    selectedPrefix,
    linkFor: (prefix: string) => inPlaceLink(hrefFor(prefix), () => onSelect(prefix))
  };
  return (
    <nav aria-labelledby={headingId} className="flex min-w-0 flex-col gap-2">
      <h2 id={headingId} className="text-sm font-semibold">
        {t("website_source_structure")}
      </h2>
      <FolderLink {...navigation} prefix="" label={t("website_source_all_content")} count={total} />
      <FolderBranch {...navigation} prefix="" />
      <p className="text-ax-text-secondary text-xs">{t("website_source_structure_hint")}</p>
    </nav>
  );
}
