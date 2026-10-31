import { useAnnounce } from "@astryxdesign/core/hooks";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Search, SearchX } from "lucide-react";
import { useEffect } from "react";
import { useTranslations } from "use-intl";
import { TextInput } from "@astryxdesign/core/TextInput";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { flattenPages } from "@/lib/api/pagination";
import { useSearchDraft } from "@/lib/hooks/use-search-draft";
import { replaceUrl, usePathname, useSearchParams } from "@/lib/navigation";
import { BlobTable } from "./blobs";
import { websiteBlobPagesQueryOptions } from "./knowledge";
import { readWebsiteContentSearch, websiteContentHref } from "./website-content-search";
import { WebsiteFolderNav } from "./website-folder-nav";

export function WebsiteContent({
  websiteId,
  labelledBy,
  total: websiteTotal
}: {
  websiteId: string;
  labelledBy: string;
  total: number;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const pathname = usePathname();
  const params = useSearchParams();
  const view = readWebsiteContentSearch(params);
  const { q, prefix, tab } = view;
  const { draft, setDraft, settled } = useSearchDraft(view.q);
  const pages = useInfiniteQuery(websiteBlobPagesQueryOptions(browserApi, websiteId, view));
  const blobs = flattenPages(pages.data?.pages);
  const total = pages.data?.pages.at(-1)?.total_count ?? 0;
  const count = t(
    total === 1 ? "website_source_content_count_one" : "website_source_content_count_other",
    { shown: blobs.length, total }
  );

  useEffect(() => {
    if (settled !== q) {
      replaceUrl(websiteContentHref(pathname, params, { tab, prefix, q: settled }));
    }
  }, [settled, q, prefix, tab, pathname, params]);

  useEffect(() => {
    if (pages.data && !pages.isFetching) announce(count);
  }, [announce, count, pages.data, pages.isFetching]);

  return (
    <div className="grid min-w-0 gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="border-ax-border max-h-72 overflow-y-auto border-b pb-4 lg:max-h-none lg:border-e lg:border-b-0 lg:pe-4">
        <WebsiteFolderNav
          websiteId={websiteId}
          total={websiteTotal}
          selectedPrefix={view.prefix}
          hrefFor={(prefix) => websiteContentHref(pathname, params, { ...view, prefix })}
          onSelect={(prefix) =>
            replaceUrl(websiteContentHref(pathname, params, { ...view, prefix }))
          }
        />
      </aside>
      <section
        className="flex min-w-0 flex-col gap-4"
        aria-labelledby={labelledBy}
        aria-busy={pages.isFetching}
      >
        <div>
          <h2 className="text-base font-semibold break-all">
            {view.prefix || t("website_source_all_content")}
          </h2>
          <p className="text-ax-text-secondary mt-1 text-sm">{t("website_source_content_hint")}</p>
        </div>
        <TextInput
          label={t("website_source_search")}
          isLabelHidden
          placeholder={t("website_source_search")}
          role="searchbox"
          value={draft}
          onChange={(value) => setDraft(value.slice(0, 200))}
          startIcon={Search}
          hasClear
          width="100%"
        />
        <QueryStateBoundary query={pages} errorTitle={t("website_source_content_load_failed")}>
          {() => (
            <>
              {blobs.length > 0 ? (
                <BlobTable
                  blobs={blobs}
                  canEdit={false}
                  labelledBy={labelledBy}
                  filterable={false}
                  paginate={false}
                />
              ) : (
                <EmptyState
                  icon={<SearchX />}
                  title={
                    view.q || view.prefix ? t("no_results_found") : t("website_no_indexed_content")
                  }
                  isCompact
                />
              )}
              <p className="text-ax-text-secondary text-sm">{count}</p>
              <LoadMore
                query={pages}
                label={t("website_indexed_content_load_more", { current: blobs.length, total })}
              />
            </>
          )}
        </QueryStateBoundary>
      </section>
    </div>
  );
}
